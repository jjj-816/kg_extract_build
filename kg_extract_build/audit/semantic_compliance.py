"""受控规范证据端口与合规结论门禁。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol
import re
import unicodedata


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
    declared = tuple(getattr(scope, "declared_families", ()) or ())
    declared_keys = {_norm_normative_identity(value) for value in declared}
    allowed_family_ids = {str(value) for value in (getattr(scope, "family_ids", ()) or ())}
    for item in result.get("evidence", ()):
        if item.get("source_type") != "spec" or not item.get("release_id"):
            continue
        if item.get("same_year_version_conflict"):
            continue
        if not item.get("text") or not item.get("version_id") or not item.get("clause_id"):
            continue
        if declared_keys and not _matches_declared(item, declared_keys, allowed_family_ids):
            continue
        selected.append(dict(item, evidence_type="normative_clause", applicability_status="candidate"))
    return tuple(selected)


def _norm_normative_identity(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[《》()（）\[\]{}\s·,，、:：;；/\\_-]+", "", text)


def _matches_declared(item: Mapping[str, Any], declared_keys: set[str], allowed_family_ids: set[str]) -> bool:
    if str(item.get("family_id", "")) in allowed_family_ids:
        return True
    values = (
        item.get("family_name"), item.get("canonical_name"), item.get("display_name"),
        item.get("standard_code_base"), item.get("standard_code"), item.get("family_id"),
    )
    if not any(value for value in values):
        return True
    keys = {_norm_normative_identity(value) for value in values if value}
    return any(key in declared_keys or key and any(key in declared or declared in key for declared in declared_keys) for key in keys)


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
