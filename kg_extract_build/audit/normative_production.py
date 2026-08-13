"""Production adapter that gates normative evidence on published metadata."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
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

    def _canonical_scope(self, scope: NormativeScope) -> NormativeScope:
        resolver = getattr(self.store, "resolve_family_ids", None)
        if resolver is None:
            return scope
        mapping = resolver((*scope.declared_families, *scope.supplemental_families))
        family_ids = tuple(dict.fromkeys(
            mapping.get(value, value)
            for value in (*scope.declared_families, *scope.supplemental_families)
        ))
        return replace(scope, family_ids=family_ids)

    def preflight(self, scope: NormativeScope, release_id: str) -> NormativeScopePreflight:
        scope = self._canonical_scope(scope)
        # Releases remain immutable build/replay snapshots.  Formal audit scope
        # comes from the explicitly enabled unified corpus instead.
        list_enabled = getattr(self.store, "list_audit_enabled_indexes", None)
        index_rows = list_enabled() if list_enabled else self.store.index_rows(
            self.store.release_member_index_ids(release_id)
        )
        index_by_version = {
            row["version_id"]: row for row in index_rows
            if row.get("status", "ready") == "ready" and not row.get("audit_disabled_at")
        }
        versions = self.store.version_candidates()
        candidates, conflicts = applicable_versions(versions, scope.audit_year, scope.family_ids, ())
        by_family: dict[str, list] = {}
        for candidate in candidates:
            if candidate.version_id in index_by_version:
                by_family.setdefault(candidate.family_id, []).append(candidate)
        return preflight_normative_scope(scope, by_family, index_by_version, conflicts)

    def search(self, *, query: str, audit_year: int, release_id: str, scope: NormativeScope, top_k: int = 5) -> dict[str, Any]:
        scope = self._canonical_scope(scope)
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
        valid = [item for item in result.get("evidence", []) if item.get("text") and item.get("version_id") and item.get("clause_id") and (not release_id or item.get("release_id") in {release_id, "enabled-corpus"})]
        result["evidence"] = valid
        result["coverage"] = [dict(item) for item in preflight.coverage]
        return result
