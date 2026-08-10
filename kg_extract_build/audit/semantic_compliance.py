"""受控规范证据端口与合规结论门禁。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class NormativeEvidenceProvider(Protocol):
    def search(self, *, query: str, scope: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ApplicabilityResult:
    clause_id: str
    version_id: str
    status: str
    reason: str
    condition_evidence: tuple[Mapping[str, Any], ...] = ()


def select_published_clause_evidence(result: Mapping[str, Any], scope) -> tuple[Mapping[str, Any], ...]:
    """Only complete, published, in-scope clauses may enter a model package."""
    if result.get("coverage") and any(item.get("coverage_status") != "covered" for item in result["coverage"]):
        return ()
    selected = []
    for item in result.get("evidence", ()):
        if item.get("source_type") != "spec" or not item.get("release_id"):
            continue
        if item.get("same_year_version_conflict"):
            continue
        if not item.get("text") or not item.get("version_id") or not item.get("clause_id"):
            continue
        selected.append(dict(item, evidence_type="normative_clause", applicability_status="candidate"))
    return tuple(selected)


def validate_compliance_conclusion(output: Mapping[str, Any], document_evidence_ids: set[str], normative_evidence: tuple[Mapping[str, Any], ...]) -> dict:
    """Prevent a compliance conclusion when its required evidence is absent."""
    status = output.get("result_status")
    if status not in {"no_issue", "issue_found", "manual_review"}:
        raise ValueError("非法合规结论")
    referenced_docs = set(output.get("document_evidence_ids", ()))
    referenced_norms = set(output.get("normative_evidence_ids", ()))
    available_norms = {str(item["clause_id"]) for item in normative_evidence}
    if not referenced_docs.issubset(document_evidence_ids) or not referenced_norms.issubset(available_norms):
        raise ValueError("合规结论引用了当前证据包之外的证据")
    if status == "issue_found" and (not referenced_docs or not referenced_norms):
        raise ValueError("不符合结论必须同时引用文档证据和规范证据")
    return dict(output)
