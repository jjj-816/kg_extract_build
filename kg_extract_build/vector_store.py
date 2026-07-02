import os

from .persistence import env_bool


class NullVectorStore:
    enabled = False

    def upsert_segments(self, records, embeddings):
        return None

    def close(self):
        return None


class MilvusSegmentStore:
    enabled = True

    def __init__(self, uri, token="", collection_name="kg_document_segments"):
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:
            raise RuntimeError("启用 Milvus 存储需要安装 pymilvus") from exc

        options = {"uri": uri}
        if token:
            options["token"] = token
        self.client = MilvusClient(**options)
        self.collection_name = collection_name

    @classmethod
    def from_env(cls):
        return cls(
            uri=os.getenv("KG_MILVUS_URI", "http://127.0.0.1:19530"),
            token=os.getenv("KG_MILVUS_TOKEN", ""),
            collection_name=os.getenv(
                "KG_MILVUS_COLLECTION",
                "kg_document_segments",
            ),
        )

    def _ensure_collection(self, dimension):
        if self.client.has_collection(collection_name=self.collection_name):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            dimension=int(dimension),
            primary_field_name="chunk_id",
            vector_field_name="embedding",
            metric_type="COSINE",
            auto_id=False,
            enable_dynamic_field=True,
        )

    def upsert_segments(self, records, embeddings):
        if not records:
            return
        vectors = [
            embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
            for embedding in embeddings
        ]
        self._ensure_collection(len(vectors[0]))
        payload = []
        for record, embedding in zip(records, vectors):
            payload.append({**record, "embedding": embedding})
        self.client.upsert(
            collection_name=self.collection_name,
            data=payload,
        )

    def close(self):
        close = getattr(self.client, "close", None)
        if callable(close):
            close()


def build_vector_store():
    if not env_bool("KG_MILVUS_ENABLED", False):
        return NullVectorStore()
    return MilvusSegmentStore.from_env()
