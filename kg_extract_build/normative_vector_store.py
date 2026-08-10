"""规范条款 Milvus 集合族封装（维度隔离，只存稳定标识+向量）。"""

from __future__ import annotations

import os
import re

from . import settings


def _slug(model_key: str, dimension: int) -> str:
    match = re.search(r"minilm|qwen3|bge-?m3", model_key, re.IGNORECASE)
    base = (match.group(0).lower().replace("-", "") if match else "model")
    return f"{base}_{dimension}"


def _read_dimension(info: dict) -> int:
    """从 pymilvus describe_collection 返回的 dict 中提取向量维度。

    pymilvus>=2.5 的 CollectionSchema.dict() 不含顶层 ``params`` 键；
    维度在 ``fields[].params.dim`` 中。这里遍历字段找到第一个向量字段的维度。
    """
    for field in info.get("fields", []):
        dim = int(field.get("params", {}).get("dim", 0) or 0)
        if dim:
            return dim
    return 0


class NormativeMilvusStore:
    def __init__(self, uri, token="", collection_prefix="kg_normative_clauses"):
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:
            raise RuntimeError("启用规范向量索引需要安装 pymilvus") from exc
        self._uri = uri
        self._token = token
        self._client_cls = MilvusClient
        self.collection_prefix = collection_prefix
        # MilvusClient 构造即发起连接；延迟到首次真正使用时再建立，
        # 保证"只在实际使用 store 时才连接真实 Milvus 服务"。
        self.client = None

    def _client(self):
        if self.client is None:
            options = {"uri": self._uri}
            if self._token:
                options["token"] = self._token
            self.client = self._client_cls(**options)
        return self.client

    @classmethod
    def from_env(cls):
        return cls(
            uri=settings.NORM_MILVUS_URI,
            token=settings.NORM_MILVUS_TOKEN,
            collection_prefix=settings.NORM_MILVUS_COLLECTION_PREFIX,
        )

    def collection_name(self, profile) -> str:
        return f"{self.collection_prefix}__{_slug(profile.embedding_model_key, profile.embedding_dimension)}__v1"

    def ensure_collection(self, profile) -> None:
        client = self._client()
        name = self.collection_name(profile)
        if client.has_collection(collection_name=name):
            info = client.describe_collection(name)
            actual_dim = _read_dimension(info)
            if actual_dim and actual_dim != profile.embedding_dimension:
                raise ValueError(f"集合 {name} 维度 {actual_dim} 与 {profile.embedding_dimension} 不匹配")
            return
        client.create_collection(
            collection_name=name,
            dimension=profile.embedding_dimension,
            primary_field_name="segment_id",
            vector_field_name="embedding",
            metric_type="COSINE",
            auto_id=False,
            enable_dynamic_field=True,
        )
        # 创建后立即验证
        info = client.describe_collection(name)
        actual_dim = _read_dimension(info)
        if actual_dim and actual_dim != profile.embedding_dimension:
            raise ValueError(f"创建后集合 {name} 维度 {actual_dim} 与 {profile.embedding_dimension} 不匹配")

    def upsert_segments(self, profile, records) -> None:
        if not records:
            return
        self.ensure_collection(profile)
        client = self._client()
        collection_name = self.collection_name(profile)
        client.upsert(
            collection_name=collection_name,
            data=records,
        )
        # Milvus upsert can be eventually visible.  Do not report an index as
        # ready before the just-written segments are made searchable.
        flush = getattr(client, "flush", None)
        if callable(flush):
            flush(collection_name=collection_name)

    def search(self, profile, query_vector, index_ids, version_ids, limit=30):
        client = self._client()
        name = self.collection_name(profile)
        filters = []
        if index_ids:
            ids = ",".join(f'"{i}"' for i in index_ids)
            filters.append(f"index_id in [{ids}]")
        if version_ids:
            ids = ",".join(f'"{v}"' for v in version_ids)
            filters.append(f"version_id in [{ids}]")
        filter_expr = " and ".join(filters)
        results = client.search(
            collection_name=name,
            data=[query_vector],
            filter=filter_expr,
            limit=int(limit),
            anns_field="embedding",
            output_fields=[
                "index_id", "clause_id", "clause_set_id", "version_id",
                "family_id", "document_id", "source_type", "clause_number", "text_hash",
            ],
        )
        hits = []
        for row in results[0]:
            entity = row.get("entity") or {}
            hits.append(
                {**entity, "score": float(row.get("distance", 0.0))}
            )
        return hits

    def close(self):
        close = getattr(self.client, "close", None)
        if callable(close):
            close()


class NullNormativeVectorStore:
    enabled = False

    def ensure_collection(self, profile):
        return None

    def upsert_segments(self, profile, records):
        return None

    def search(self, profile, query_vector, index_ids, version_ids, limit=30):
        return []

    def close(self):
        return None


def build_normative_vector_store():
    if not settings.NORM_MILVUS_ENABLED:
        return NullNormativeVectorStore()
    return NormativeMilvusStore.from_env()
