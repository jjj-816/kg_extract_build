"""Immutable normative-clause primitives used by the vector-index workflow."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterable


PARSER_VERSION = "normative-clause-v1"
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_LAW_RE = re.compile(r"^第[一二三四五六七八九十百千万零〇0-9]+条(?:\s*.*)?$", re.MULTILINE)
_NUMBERED_RE = re.compile(r"^\d+(?:\.\d+){1,3}(?:\s+.*)?$", re.MULTILINE)


def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_clause_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in str(text).strip().splitlines()).strip()


@dataclass(frozen=True)
class ClauseDraft:
    clause_number: str | None
    hierarchy_path: tuple[str, ...]
    clause_title: str | None
    raw_text: str
    normalized_text: str
    start_offset: int
    end_offset: int
    parse_status: str

    @property
    def content_hash(self) -> str:
        return stable_hash({"text": self.raw_text, "path": self.hierarchy_path})


@dataclass(frozen=True)
class NormativeVersionCandidate:
    version_id: str
    family_id: str
    effective_year: int
    invalid_year: int | None
    metadata_confirmed: bool
    status: str

    def applies_in(self, audit_year: int) -> bool:
        return (
            self.metadata_confirmed
            and self.effective_year <= audit_year
            and (self.invalid_year is None or self.invalid_year >= audit_year)
        )


def parse_normative_clauses(text: str) -> list[ClauseDraft]:
    """Parse legal and dotted clauses while retaining exact source offsets.

    Headings provide hierarchy only. If no stable clause number exists, the
    parser falls back to non-empty paragraph blocks so a source can still be
    inspected without pretending that a heading is a normative requirement.
    """
    text = str(text or "")
    heading_matches = list(_HEADING_RE.finditer(text))
    numbered = sorted(
        [*list(_LAW_RE.finditer(text)), *list(_NUMBERED_RE.finditer(text))],
        key=lambda match: match.start(),
    )
    if not numbered:
        return _fallback_clauses(text, heading_matches)

    clauses: list[ClauseDraft] = []
    for index, match in enumerate(numbered):
        end = numbered[index + 1].start() if index + 1 < len(numbered) else len(text)
        raw = text[match.start():end].strip()
        if not raw:
            continue
        line = match.group(0).strip()
        number = line.split(maxsplit=1)[0]
        title = line[len(number):].strip() or None
        path = _heading_path(heading_matches, match.start())
        clauses.append(
            ClauseDraft(
                clause_number=number,
                hierarchy_path=path,
                clause_title=title,
                raw_text=raw,
                normalized_text=normalize_clause_text(raw),
                start_offset=match.start(),
                end_offset=end,
                parse_status="structured",
            )
        )
    return clauses


def _heading_path(matches: list[re.Match[str]], offset: int) -> tuple[str, ...]:
    stack: list[tuple[int, str]] = []
    for match in matches:
        if match.start() >= offset:
            break
        level = len(match.group(1))
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, match.group(2).strip()))
    return tuple(title for _, title in stack)


def _fallback_clauses(text: str, headings: list[re.Match[str]]) -> list[ClauseDraft]:
    drafts = []
    for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, re.DOTALL):
        raw = match.group(0).strip()
        if not raw or _HEADING_RE.fullmatch(raw):
            continue
        drafts.append(
            ClauseDraft(
                clause_number=None,
                hierarchy_path=_heading_path(headings, match.start()),
                clause_title=None,
                raw_text=raw,
                normalized_text=normalize_clause_text(raw),
                start_offset=match.start(),
                end_offset=match.end(),
                parse_status="fallback",
            )
        )
    return drafts


def build_index_fingerprint(
    *, document_content_hash: str, metadata_hash: str, clause_set_id: str,
    chunk_config: dict[str, object], embedding_model_revision: str,
    encoder_profile_hash: str, embedding_dimension: int,
) -> str:
    return stable_hash({
        "document_content_hash": document_content_hash,
        "metadata_hash": metadata_hash,
        "clause_set_id": clause_set_id,
        "chunk_config": chunk_config,
        "embedding_model_revision": embedding_model_revision,
        "encoder_profile_hash": encoder_profile_hash,
        "embedding_dimension": embedding_dimension,
    })


def applicable_versions(
    versions: Iterable[NormativeVersionCandidate], audit_year: int,
    allowed_family_ids: Iterable[str] = (), allowed_version_ids: Iterable[str] = (),
) -> tuple[list[NormativeVersionCandidate], dict[str, bool]]:
    allowed_families = set(allowed_family_ids)
    allowed_versions = set(allowed_version_ids)
    result = [
        version for version in versions
        if version.applies_in(audit_year)
        and (not allowed_families or version.family_id in allowed_families)
        and (not allowed_versions or version.version_id in allowed_versions)
    ]
    conflicts = {
        family_id: len(items) > 1
        for family_id, items in _group_by_family(result).items()
    }
    return result, conflicts


def _group_by_family(versions: Iterable[NormativeVersionCandidate]):
    grouped: dict[str, list[NormativeVersionCandidate]] = {}
    for version in versions:
        grouped.setdefault(version.family_id, []).append(version)
    return grouped
