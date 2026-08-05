"""纯向量检索预览：年份过滤 + 覆盖状态 + segment 聚合去重 + 扩窗。"""

from __future__ import annotations

from dataclasses import dataclass

from .normative import applicable_versions
from .normative_coverage import compute_coverage

BASE_OVERSAMPLE = 3
MIN_RAW_LIMIT = 30
MAX_RAW_LIMIT = 300


@dataclass(frozen=True)
class SearchRequest:
    query: str
    audit_year: int
    release_id: str
    norm_scope: dict
    top_k: int


class NormativeSearcher:
    def __init__(self, store, vector_store, encoder, profile):
        self.store = store
        self.vector_store = vector_store
        self.encoder = encoder
        self.profile = profile

    def search(self, request: SearchRequest) -> dict:
        index_ids = self.store.release_member_index_ids(request.release_id)
        if not index_ids:
            return {
                "coverage": [],
                "evidence": [],
                "retrieval_trace": {"raw_segment_limit": 0, "raw_segment_count": 0, "unique_clause_count": 0, "stop_reason": "release_empty"},
                "warnings": [f"发布版 {request.release_id} 无成员索引"],
            }

        scope = request.norm_scope or {}
        allowed_families = tuple(scope.get("allowed_family_ids") or ())
        allowed_versions = tuple(scope.get("allowed_version_ids") or ())
        versions = self.store.version_candidates()
        candidates, conflicts = applicable_versions(
            versions, request.audit_year, allowed_families, allowed_versions,
        )
        index_rows = self.store.index_rows(index_ids)
        index_by_version = {r["version_id"]: r for r in index_rows}
        version_index_map = {r["version_id"]: r["index_id"] for r in index_rows}

        target_versions = [v.version_id for v in candidates if v.version_id in version_index_map]

        coverage = []
        if scope.get("scope_type") == "declared":
            # 覆盖状态基于审核年份过滤后的候选版本（与原设计 §12.3 一致）
            candidates_by_family = {}
            for v in candidates:
                candidates_by_family.setdefault(v.family_id, []).append(v)
            requested = [f for f in allowed_families]
            coverage = compute_coverage(candidates_by_family, version_index_map, requested, conflicts)

        query_vector = self.encoder.encode_query(request.query)
        raw_limit = max(request.top_k * BASE_OVERSAMPLE, MIN_RAW_LIMIT)
        unique: dict[int, dict] = {}
        raw_segment_count = 0
        stop_reason = "ok"
        while raw_limit <= MAX_RAW_LIMIT:
            hits = self.vector_store.search(
                self.profile, query_vector, version_index_map and list(version_index_map.values()),
                target_versions, limit=raw_limit,
            )
            raw_segment_count += len(hits)
            for hit in hits:
                clause_id = hit.get("clause_id")
                if clause_id is None:
                    continue
                if clause_id not in unique or hit.get("score", 0) > unique[clause_id]["score"]:
                    unique[clause_id] = hit
            if len(unique) >= request.top_k or len(hits) < raw_limit:
                break
            if raw_limit == MAX_RAW_LIMIT:
                stop_reason = "safety_cap"
                break
            raw_limit = min(raw_limit * 2, MAX_RAW_LIMIT)
        if raw_segment_count and not unique:
            stop_reason = "no_hits"

        ranked = sorted(unique.values(), key=lambda r: r.get("score", 0), reverse=True)
        evidence = []
        for rank, hit in enumerate(ranked[: request.top_k], start=1):
            clause = self._fetch_clause(hit.get("clause_set_id"), hit.get("clause_id"))
            evidence.append(
                {
                    "release_id": request.release_id,
                    "index_id": hit.get("index_id"),
                    "family_id": hit.get("family_id"),
                    "version_id": hit.get("version_id"),
                    "clause_set_id": hit.get("clause_set_id"),
                    "clause_id": hit.get("clause_id"),
                    "clause_number": hit.get("clause_number"),
                    "text": clause["raw_text"] if clause else "",
                    "clause_content_hash": clause.get("content_hash") if clause else hit.get("text_hash"),
                    "score": hit.get("score", 0),
                    "rank": rank,
                    "source_type": "spec",
                    "same_year_version_conflict": bool(conflicts.get(hit.get("family_id"))),
                    "hit_segment_ids": [hit.get("text_hash")],
                }
            )

        return {
            "coverage": coverage,
            "evidence": evidence,
            "retrieval_trace": {
                "raw_segment_limit": raw_limit,
                "raw_segment_count": raw_segment_count,
                "unique_clause_count": len(unique),
                "stop_reason": stop_reason,
            },
            "warnings": [],
        }

    def _fetch_clause(self, clause_set_id, clause_id):
        if not clause_set_id:
            return None
        for row in self.store.get_clauses(clause_set_id):
            if row.get("clause_id") == clause_id:
                return row
        return None
