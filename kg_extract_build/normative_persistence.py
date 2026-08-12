"""规范族/版本/条款集/条款的 MySQL 持久化（只写已有 schema 表）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .normative import ClauseDraft, NormativeVersionCandidate, stable_hash, text_hash_int64
from .normative_meta import FamilyDraft, VersionDraft


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


class NormativeStore:
    """薄封装：把所有 SQL 委托给 backend（MySQLExperimentStore 满足接口）。"""

    def __init__(self, backend):
        self._backend = backend

    def _read(self, sql, params=None):
        return self._backend._read(sql, params)

    def _write(self, sql, params=None, many=False):
        return self._backend._write(sql, params, many=many)

    # ---- 族与版本 ----
    def save_family(self, family_id: str, family: FamilyDraft) -> None:
        self._backend._write(
            "INSERT INTO kg_normative_family "
            "(family_id, canonical_name, standard_code_base, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (family_id, family.canonical_name, family.standard_code_base, _utc_now(), _utc_now()),
        )

    def save_version(self, draft: VersionDraft) -> str:
        version_id = draft.version_id or str(uuid.uuid4())
        self._backend._write(
            "INSERT INTO kg_normative_version "
            "(version_id, family_id, document_id, display_name, standard_code, "
            " version_year, publication_year, effective_year, invalid_year, status, "
            " supersedes_version_id, metadata_confirmed, metadata_hash, confirmed_at, "
            " created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                version_id, draft.family_id, draft.document_id, draft.display_name,
                draft.standard_code, draft.version_year, draft.publication_year,
                draft.effective_year, draft.invalid_year, draft.status,
                draft.supersedes_version_id, int(draft.metadata_confirmed),
                draft.metadata_hash,
                _utc_now() if draft.metadata_confirmed else None,
                _utc_now(), _utc_now(),
            ),
        )
        return version_id

    def get_version(self, version_id: str) -> dict | None:
        rows = self._backend._read(
            "SELECT * FROM kg_normative_version WHERE version_id=%s", (version_id,)
        )
        return rows[0] if rows else None

    def list_versions(self, family_id: str | None = None) -> list[dict]:
        if family_id is None:
            return self._backend._read("SELECT * FROM kg_normative_version")
        return self._backend._read(
            "SELECT * FROM kg_normative_version WHERE family_id=%s", (family_id,)
        )

    def version_candidates(self) -> list[NormativeVersionCandidate]:
        rows = self._backend._read("SELECT * FROM kg_normative_version")
        return [
            NormativeVersionCandidate(
                version_id=r["version_id"],
                family_id=r["family_id"],
                effective_year=r["effective_year"],
                invalid_year=r["invalid_year"],
                metadata_confirmed=bool(r["metadata_confirmed"]),
                status=r["status"],
            )
            for r in rows
            if r["metadata_confirmed"]
        ]

    # ---- 条款集与条款 ----
    def save_clause_set(
        self, clause_set_id, version_id, document_id, source_content_hash,
        parser_version, parser_config_hash, status,
    ) -> None:
        self._backend._write(
            "INSERT INTO kg_normative_clause_set "
            "(clause_set_id, version_id, document_id, source_content_hash, "
            " parser_version, parser_config_hash, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (clause_set_id, version_id, document_id, source_content_hash,
             parser_version, parser_config_hash, status, _utc_now()),
        )

    def save_clauses(self, clause_set_id, version_id, document_id, clauses) -> None:
        params = []
        for clause in clauses:
            params.append(
                (clause_set_id, version_id, document_id, clause.clause_number,
                 _json(clause.hierarchy_path), clause.clause_title,
                 clause.raw_text, clause.normalized_text,
                 clause.start_offset, clause.end_offset, clause.content_hash,
                 clause.parse_status, _utc_now())
            )
        self._backend._write(
            "INSERT INTO kg_normative_clause "
            "(clause_set_id, version_id, document_id, clause_number, hierarchy_path, "
            " clause_title, raw_text, normalized_text, start_offset, end_offset, "
            " content_hash, parse_status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            params,
            many=True,
        )

    def get_clauses(self, clause_set_id) -> list[dict]:
        return self._backend._read(
            "SELECT * FROM kg_normative_clause WHERE clause_set_id=%s", (clause_set_id,)
        )

    # ---- 条款集查询 ----
    def latest_clause_set(self, version_id: str) -> dict | None:
        rows = self._backend._read(
            "SELECT * FROM kg_normative_clause_set "
            "WHERE version_id=%s AND status='published' "
            "ORDER BY created_at DESC LIMIT 1",
            (version_id,),
        )
        return rows[0] if rows else None

    # ---- 索引 ----
    def save_index(self, record: dict) -> None:
        import json
        self._backend._write(
            "INSERT INTO kg_normative_index "
            "(index_id, version_id, clause_set_id, collection_name, embedding_model_key, "
            " embedding_model_revision, embedding_dimension, encoder_profile_json, encoder_profile_hash, "
            " metric_type, chunker_version, chunk_config_json, index_fingerprint, "
            " status, error_message, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE "
            "index_id=VALUES(index_id), "
            "clause_set_id=VALUES(clause_set_id), "
            "collection_name=VALUES(collection_name), "
            "embedding_model_key=VALUES(embedding_model_key), "
            "embedding_model_revision=VALUES(embedding_model_revision), "
            "embedding_dimension=VALUES(embedding_dimension), "
            "encoder_profile_json=VALUES(encoder_profile_json), "
            "encoder_profile_hash=VALUES(encoder_profile_hash), "
            "metric_type=VALUES(metric_type), "
            "chunker_version=VALUES(chunker_version), "
            "chunk_config_json=VALUES(chunk_config_json), "
            "status=VALUES(status), "
            "error_message=VALUES(error_message)",
            (record["index_id"], record["version_id"], record["clause_set_id"],
             record["collection_name"], record["embedding_model_key"],
             record["embedding_model_revision"], record["embedding_dimension"],
             record["encoder_profile_json"], record["encoder_profile_hash"],
             record["metric_type"],
             record["chunker_version"],
             json.dumps(record.get("chunk_config_json") or {}, ensure_ascii=False),
             record["index_fingerprint"], record["status"],
             record.get("error_message"), _utc_now()),
        )

    def get_index_by_fingerprint(self, fingerprint: str) -> dict | None:
        rows = self._backend._read(
            "SELECT * FROM kg_normative_index WHERE index_fingerprint=%s AND status='ready'",
            (fingerprint,),
        )
        return rows[0] if rows else None

    def save_segments(self, index_id: str, segments) -> None:
        params = [
            (index_id, clause_row["clause_id"], draft.segment_index,
             draft.embedding_text, draft.token_count, draft.text_hash,
             str(text_hash_int64(draft.text_hash)), _utc_now())
            for clause_row, draft in segments
        ]
        self._backend._write(
            "INSERT INTO kg_normative_index_segment "
            "(index_id, clause_id, segment_index, embedding_text, token_count, "
            " text_hash, milvus_vector_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            params, many=True,
        )

    # ---- 发布 ----
    def save_release(self, record: dict) -> None:
        self._backend._write(
            "INSERT INTO kg_normative_index_release "
            "(release_id, release_name, collection_name, embedding_model_key, "
            " embedding_model_revision, encoder_profile_hash, release_fingerprint, "
            " status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (record["release_id"], record["release_name"], record["collection_name"],
             record["embedding_model_key"], record["embedding_model_revision"],
             record["encoder_profile_hash"], record["release_fingerprint"],
             record["status"], _utc_now()),
        )

    def save_release_member(self, release_id: str, index_id: str, version_id: str, clause_set_id: str) -> None:
        self._backend._write(
            "INSERT INTO kg_normative_index_release_member "
            "(release_id, index_id, version_id, clause_set_id, included_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (release_id, index_id, version_id, clause_set_id, _utc_now()),
        )

    def release_member_index_ids(self, release_id: str) -> list[str]:
        rows = self._backend._read(
            "SELECT index_id FROM kg_normative_index_release_member WHERE release_id=%s",
            (release_id,),
        )
        return [r["index_id"] for r in rows]

    def index_rows(self, index_ids: list[str]) -> list[dict]:
        if not index_ids:
            return []
        placeholders = ",".join(["%s"] * len(index_ids))
        return self._backend._read(
            f"SELECT * FROM kg_normative_index WHERE index_id IN ({placeholders})", list(index_ids)
        )

    def list_audit_enabled_indexes(self) -> list[dict]:
        """Return the explicit unified-corpus membership, independent of releases."""
        return self._backend._read(
            "SELECT * FROM kg_normative_index "
            "WHERE status='ready' AND enabled_for_audit=1"
        )

    def set_audit_enabled(self, index_id: str, enabled: bool) -> None:
        self._backend._write(
            "UPDATE kg_normative_index SET enabled_for_audit=%s WHERE index_id=%s",
            (int(bool(enabled)), index_id),
        )

    # ---- 生命周期 ----
    def has_normative_references(self, document_id: int) -> bool:
        for table in ("kg_normative_version", "kg_normative_clause_set", "kg_normative_clause"):
            rows = self._backend._read(
                f"SELECT 1 FROM {table} WHERE document_id=%s LIMIT 1", (document_id,)
            )
            if rows:
                return True
        return False


def _json(value):
    import json
    return json.dumps(list(value or ()), ensure_ascii=False)
