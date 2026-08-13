"""冻结语义审核运行所使用的规范范围并执行覆盖预检。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from kg_extract_build.normative import NormativeVersionCandidate
from kg_extract_build.normative_coverage import compute_coverage


@dataclass(frozen=True)
class NormativeScope:
    audit_year: int
    declared_families: tuple[str, ...]
    supplemental_families: tuple[str, ...]
    family_ids: tuple[str, ...]
    work_types: tuple[str, ...]

    @classmethod
    def freeze(cls, audit_year: int, declared_families: Iterable[str], supplemental_families: Iterable[str], work_types: Iterable[str] = ()):
        declared = tuple(dict.fromkeys(str(item) for item in declared_families if str(item).strip()))
        supplemental = tuple(dict.fromkeys(str(item) for item in supplemental_families if str(item).strip()))
        return cls(audit_year, declared, supplemental, tuple(dict.fromkeys((*declared, *supplemental))), tuple(dict.fromkeys(str(item) for item in work_types if str(item).strip())))


@dataclass(frozen=True)
class NormativeScopePreflight:
    scope: NormativeScope
    coverage: tuple[Mapping[str, Any], ...]
    blocked: bool
    blocking_reasons: tuple[str, ...]

    @property
    def can_start_compliance(self) -> bool:
        return not self.blocked

    def display_summary(self) -> dict[str, Any]:
        return {
            "审核基准年份": self.scope.audit_year,
            "声明规范": list(self.scope.declared_families),
            "补充规范": list(self.scope.supplemental_families),
            "覆盖状态": [dict(item) for item in self.coverage],
            "是否阻塞合规审核": self.blocked,
            "阻塞原因": list(self.blocking_reasons),
        }


def preflight_normative_scope(
    scope: NormativeScope,
    candidates_by_family: Mapping[str, Iterable[NormativeVersionCandidate]],
    version_index_map: Mapping[str, Any],
    conflicts: Mapping[str, bool] | None = None,
) -> NormativeScopePreflight:
    """Return an auditable, frozen preflight result.

    Coverage is advisory: formal compliance first retrieves from the unified
    corpus, then applies declared-norm and applicability filters per task.
    """
    conflicts = conflicts or {}
    coverage = compute_coverage(candidates_by_family, version_index_map, scope.family_ids, conflicts)
    reasons: list[str] = []
    for item in coverage:
        family = item["family_id"]
        status = item["coverage_status"]
        if status != "covered":
            reasons.append(f"规范 {family} 覆盖状态为 {status}")
        if item.get("same_year_version_conflict"):
            reasons.append(f"规范 {family} 存在同年版本冲突，需人工确认")
        candidates = tuple(candidates_by_family.get(family, ()))
        for candidate in candidates:
            if not candidate.metadata_confirmed:
                reasons.append(f"规范 {family} 的版本 {candidate.version_id} 尚未确认适用")
            if not candidate.applies_in(scope.audit_year):
                reasons.append(f"规范 {family} 的版本 {candidate.version_id} 不适用于审核年份 {scope.audit_year}")
    frozen_coverage = tuple(MappingProxyType(dict(item)) for item in coverage)
    return NormativeScopePreflight(scope, frozen_coverage, False, tuple(dict.fromkeys(reasons)))
