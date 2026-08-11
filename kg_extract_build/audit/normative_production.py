"""Production adapter that gates normative evidence on published metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..normative import applicable_versions
from ..normative_search import NormativeSearcher, SearchRequest
from .normative_scope import NormativeScope, NormativeScopePreflight, preflight_normative_scope


@dataclass(frozen=True)
class NormativeAdapterDiagnostic:
    status: str
    message: str


class PublishedNormativeAdapter:
    """Compose MySQL metadata and the published Milvus release into one seam."""

    def __init__(self, store, searcher: NormativeSearcher):
        self.store = store
        self.searcher = searcher

    def preflight(self, scope: NormativeScope, release_id: str) -> NormativeScopePreflight:
        index_ids = self.store.release_member_index_ids(release_id)
        index_rows = self.store.index_rows(index_ids)
        index_by_version = {row["version_id"]: row for row in index_rows if row.get("status") == "ready"}
        versions = self.store.version_candidates()
        candidates, conflicts = applicable_versions(versions, scope.audit_year, scope.family_ids, ())
        by_family: dict[str, list] = {}
        for candidate in candidates:
            if candidate.version_id in index_by_version:
                by_family.setdefault(candidate.family_id, []).append(candidate)
        return preflight_normative_scope(scope, by_family, index_by_version, conflicts)

    def search(self, *, query: str, audit_year: int, release_id: str, scope: NormativeScope, top_k: int = 5) -> dict[str, Any]:
        preflight = self.preflight(scope, release_id)
        if preflight.blocked:
            return {
                "coverage": [dict(item) for item in preflight.coverage],
                "evidence": [],
                "warnings": list(preflight.blocking_reasons),
                "diagnostic": NormativeAdapterDiagnostic("coverage_blocked", "规范覆盖或适用性未通过预检").__dict__,
            }
        try:
            result = self.searcher.search(SearchRequest(query, audit_year, release_id, {
                "scope_type": "declared", "allowed_family_ids": scope.family_ids,
            }, top_k))
        except Exception as exc:
            return {"coverage": [dict(item) for item in preflight.coverage], "evidence": [], "warnings": [f"规范检索服务不可用：{exc}"], "diagnostic": {"status": "unavailable", "message": str(exc)}}
        valid = [item for item in result.get("evidence", []) if item.get("text") and item.get("version_id") and item.get("clause_id") and item.get("release_id") == release_id]
        result["evidence"] = valid
        result["coverage"] = [dict(item) for item in preflight.coverage]
        return result
