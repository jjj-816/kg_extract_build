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


def filter_clause_candidates(
    result: Mapping[str, Any], scope,
) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...], tuple[str, ...]]:
    """Explain the terminal evidence decision for every recalled clause.

    Retrieval intentionally searches the enabled unified corpus broadly.  A
    declaration is therefore a post-retrieval evidence filter, never a query
    gate or an applicability-preflight blocker.
    """
    selected: list[Mapping[str, Any]] = []
    trace: list[Mapping[str, Any]] = []
    warnings: list[str] = []
    declared = tuple(getattr(scope, "declared_families", ()) or ())
    declared_keys = {_norm_normative_identity(value) for value in declared}
    for item in result.get("evidence", ()):
        candidate = dict(item)
        declared_match = scope is None or bool(declared_keys) and _matches_declared(candidate, declared_keys)
        version_valid = _version_is_valid(candidate, getattr(scope, "audit_year", None))
        substitute_chain_valid = _substitute_chain_is_valid(candidate)
        clause_complete = bool(
            candidate.get("source_type") == "spec"
            and candidate.get("release_id")
            and candidate.get("text")
            and candidate.get("version_id")
            and candidate.get("clause_id")
        )
        applicability = _applicability_status(candidate)
        filter_reason = _candidate_filter_reason(
            declared_match=declared_match,
            version_valid=version_valid,
            substitute_chain_valid=substitute_chain_valid,
            clause_complete=clause_complete,
            applicability=applicability,
        )
        selection = "selected" if filter_reason is None else "filtered"
        trace.append({
            "clause_id": candidate.get("clause_id"),
            "version_id": candidate.get("version_id"),
            "family_id": candidate.get("family_id"),
            "standard_or_name_match": declared_match,
            "version_valid": version_valid,
            "same_year_substitute_chain_valid": substitute_chain_valid,
            "clause_complete": clause_complete,
            "applicability": applicability,
            "selection": selection,
            "filter_reason": filter_reason,
        })
        if filter_reason is None:
            selected.append(dict(candidate, evidence_type="normative_clause", applicability_status="candidate"))
        elif filter_reason == "not_declared_norm":
            warnings.append("declared_norm_omission")
    return tuple(selected), tuple(trace), tuple(dict.fromkeys(warnings))


def select_published_clause_evidence(result: Mapping[str, Any], scope) -> tuple[Mapping[str, Any], ...]:
    """Compatibility wrapper for callers needing only conclusion evidence."""
    return filter_clause_candidates(result, scope)[0]


def _candidate_filter_reason(*, declared_match, version_valid, substitute_chain_valid, clause_complete, applicability):
    if not clause_complete:
        return "incomplete_clause"
    if not version_valid:
        return "invalid_version"
    if not substitute_chain_valid:
        return "same_year_substitute_chain_invalid"
    if not declared_match:
        return "not_declared_norm"
    if applicability != "applicable":
        return "not_applicable"
    return None


def _version_is_valid(item: Mapping[str, Any], audit_year: int | None) -> bool:
    if item.get("same_year_version_conflict"):
        return False
    if item.get("metadata_confirmed") is not True or item.get("audit_disabled_at"):
        return False
    if item.get("index_status") != "ready":
        return False
    if item.get("version_status") != "effective":
        return False
    if audit_year is not None:
        effective = item.get("effective_year")
        invalid = item.get("invalid_year")
        if effective is not None and int(effective) > audit_year:
            return False
        if invalid is not None and int(invalid) < audit_year:
            return False
    return item.get("version_valid") is not False


def _substitute_chain_is_valid(item: Mapping[str, Any]) -> bool:
    return not any(item.get(key) is False for key in (
        "same_year_substitute_chain_valid", "substitute_chain_valid", "substitution_valid",
    ))


def _applicability_status(item: Mapping[str, Any]) -> str:
    value = item.get("applicability") or item.get("applicability_status") or "applicable"
    return "applicable" if value in {True, "applicable", "candidate", "passed"} else str(value)


def _norm_normative_identity(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[《》()（）\[\]{}\s·,，、:：;；/\\_-]+", "", text)


def _matches_declared(item: Mapping[str, Any], declared_keys: set[str]) -> bool:
    values = (
        item.get("family_name"), item.get("canonical_name"), item.get("display_name"),
        item.get("standard_code_base"), item.get("standard_code"), item.get("family_id"),
    )
    version_id = str(item.get("version_id", ""))
    if re.match(r"^(?:[A-Za-z]{2,4}\d+|[A-Za-z]{1,4}/[A-Za-z]{1,4}\d+)(?:-\d{4})?$", version_id):
        values = (*values, version_id)
    if not any(value for value in values):
        return False
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
