"""规范索引构建/重建：幂等指纹 + 状态机，失败不影响三元组实验。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .normative import build_index_fingerprint, stable_hash
from .normative_encoder import build_encoder_profile_hash
from .normative_persistence import NormativeStore
from .normative_segmentation import SegmentDraft, segment_clause


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


class NormativeIndexer:
    def __init__(self, store: NormativeStore, vector_store, encoder, profile):
        self.store = store
        self.vector_store = vector_store
        self.encoder = encoder
        self.profile = profile

    def build_index(self, version_id: str) -> dict:
        version = self.store.get_version(version_id)
        if version is None:
            return {"status": "failed", "index_id": None, "reason": f"版本不存在：{version_id}"}
        clause_set = self.store.latest_clause_set(version_id)
        if clause_set is None:
            return {"status": "failed", "index_id": None, "reason": "版本未解析出条款集，无法构建索引"}
        clauses = self.store.get_clauses(clause_set["clause_set_id"])
        if not clauses:
            return {"status": "failed", "index_id": None, "reason": "条款解析为空，无法构建索引"}

        clause_set_id = clause_set["clause_set_id"]
        fingerprint = build_index_fingerprint(
            document_content_hash=stable_hash({"doc": version["document_id"]}),
            metadata_hash=version["metadata_hash"],
            clause_set_id=clause_set_id,
            chunk_config={"max_tokens": self.profile.max_input_tokens, "overlap": 8},
            embedding_model_revision=self.profile.embedding_model_revision,
            encoder_profile_hash=build_encoder_profile_hash(self.profile),
            embedding_dimension=self.profile.embedding_dimension,
        )
        existing = self.store.get_index_by_fingerprint(fingerprint)
        if existing is not None:
            return {"status": "skipped", "index_id": existing["index_id"], "reason": "指纹幂等，跳过重建"}

        index_id = str(uuid.uuid4())
        try:
            segments = self._build_segments(version, clauses)
            texts = [draft.embedding_text for _, draft in segments]
            embeddings = self.encoder.encode_documents(texts)
            records = self._build_records(version, clauses, segments, index_id, embeddings)
            self.vector_store.ensure_collection(self.profile)
            self.vector_store.upsert_segments(self.profile, records)
            self.store.save_index(
                {
                    "index_id": index_id, "version_id": version_id,
                    "clause_set_id": clause_set_id,
                    "collection_name": self.vector_store.collection_name(self.profile),
                    "embedding_model_key": self.profile.embedding_model_key,
                    "embedding_model_revision": self.profile.embedding_model_revision,
                    "embedding_dimension": self.profile.embedding_dimension,
                    "encoder_profile_json": json.dumps({
                        "embedding_model_key": self.profile.embedding_model_key,
                        "embedding_model_revision": self.profile.embedding_model_revision,
                        "embedding_dimension": self.profile.embedding_dimension,
                        "query_prefix": self.profile.query_prefix,
                        "document_prefix": self.profile.document_prefix,
                        "pooling": self.profile.pooling,
                        "normalize": self.profile.normalize,
                        "max_input_tokens": self.profile.max_input_tokens,
                    }, ensure_ascii=False),
                    "encoder_profile_hash": build_encoder_profile_hash(self.profile),
                    "metric_type": "COSINE",
                    "chunker_version": "normative-clause-v1",
                    "chunk_config_json": {"max_tokens": self.profile.max_input_tokens, "overlap": 8},
                    "index_fingerprint": fingerprint,
                    "status": "ready",
                    "error_message": None,
                }
            )
            self.store.save_segments(index_id, segments)
            return {"status": "ready", "index_id": index_id, "reason": ""}
        except Exception as exc:
            self.store.save_index(
                {
                    "index_id": index_id, "version_id": version_id,
                    "clause_set_id": clause_set_id,
                    "collection_name": self.vector_store.collection_name(self.profile),
                    "embedding_model_key": self.profile.embedding_model_key,
                    "embedding_model_revision": self.profile.embedding_model_revision,
                    "embedding_dimension": self.profile.embedding_dimension,
                    "encoder_profile_json": json.dumps({
                        "embedding_model_key": self.profile.embedding_model_key,
                        "embedding_model_revision": self.profile.embedding_model_revision,
                        "embedding_dimension": self.profile.embedding_dimension,
                        "query_prefix": self.profile.query_prefix,
                        "document_prefix": self.profile.document_prefix,
                        "pooling": self.profile.pooling,
                        "normalize": self.profile.normalize,
                        "max_input_tokens": self.profile.max_input_tokens,
                    }, ensure_ascii=False),
                    "encoder_profile_hash": build_encoder_profile_hash(self.profile),
                    "metric_type": "COSINE",
                    "chunker_version": "normative-clause-v1",
                    "chunk_config_json": {"max_tokens": self.profile.max_input_tokens, "overlap": 8},
                    "index_fingerprint": fingerprint,
                    "status": "failed",
                    "error_message": str(exc),
                }
            )
            return {"status": "failed", "index_id": index_id, "reason": str(exc)}

    def _build_segments(self, version, clauses):
        family_name = version.get("display_name") or version["version_id"]
        segments = []
        for clause in clauses:
            segment_drafts = segment_clause(
                _to_clause_draft(clause),
                family_name=family_name,
                tokenizer=self.encoder.tokenize,
                max_tokens=self.profile.max_input_tokens,
                overlap_tokens=8,
            )
            for draft in segment_drafts:
                segments.append((clause, draft))
        return segments

    def _build_records(self, version, clauses, segments, index_id, embeddings):
        records = []
        for (clause, draft), embedding in zip(segments, embeddings):
            records.append(
                {
                    "segment_id": draft.text_hash[:16],
                    "index_id": index_id,
                    "clause_id": clause["clause_id"],
                    "clause_set_id": clause["clause_set_id"],
                    "version_id": version["version_id"],
                    "family_id": version["family_id"],
                    "document_id": version["document_id"],
                    "source_type": "spec",
                    "clause_number": clause["clause_number"],
                    "text_hash": draft.text_hash,
                    "embedding": embedding,
                }
            )
        return records

    def build_release(self, release_name: str, index_ids: list[str]) -> str:
        release_id = str(uuid.uuid4())
        self.store.save_release(
            {
                "release_id": release_id,
                "release_name": release_name,
                "collection_name": self.vector_store.collection_name(self.profile),
                "embedding_model_key": self.profile.embedding_model_key,
                "embedding_model_revision": self.profile.embedding_model_revision,
                "encoder_profile_hash": build_encoder_profile_hash(self.profile),
                "release_fingerprint": stable_hash({"name": release_name, "index_ids": sorted(index_ids)}),
                "status": "published",
            }
        )
        for row in self.store.index_rows(index_ids):
            self.store.save_release_member(
                release_id, row["index_id"], row["version_id"], row["clause_set_id"],
            )
        return release_id


def _to_clause_draft(row: dict):
    from .normative import ClauseDraft
    return ClauseDraft(
        clause_number=row.get("clause_number"),
        hierarchy_path=tuple(row.get("hierarchy_path") or ()),
        clause_title=row.get("clause_title"),
        raw_text=row.get("raw_text") or "",
        normalized_text=row.get("normalized_text") or "",
        start_offset=row.get("start_offset") or 0,
        end_offset=row.get("end_offset") or 0,
        parse_status=row.get("parse_status") or "fallback",
    )
