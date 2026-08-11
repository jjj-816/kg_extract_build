"""Evidence-preserving recognition of declared normative references."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class NormativeCandidate:
    candidate_id: str
    value: str
    source_block_id: str
    source_locator: str
    evidence_text: str
    match_type: str
    confirmed: bool = False


_PATTERNS = (
    ("book_title", re.compile(r"《[^》]{2,80}》")),
    ("standard_code", re.compile(r"\b(?:GB|GB/T|JGJ|JTG|DL|SY|Q/[^\s，。；;]{1,20})\s*[A-Z0-9./-]{2,30}(?:[-—]\d{4})?\b", re.I)),
    ("reference_phrase", re.compile(r"(?:依据|按照|遵照|参照)\s*[^，。；;\n]{2,80}")),
)


def recognize_declared_norms(blocks: Iterable[object]) -> tuple[NormativeCandidate, ...]:
    candidates: list[NormativeCandidate] = []
    seen: set[tuple[str, str]] = set()
    for block in blocks:
        text = str(getattr(block, "raw_text", "") or "")
        for match_type, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0).strip()
                key = (value, str(getattr(block, "block_id", "")))
                if not value or key in seen:
                    continue
                seen.add(key)
                block_id = str(getattr(block, "block_id", ""))
                candidates.append(NormativeCandidate(
                    candidate_id=f"norm-{len(candidates) + 1}", value=value,
                    source_block_id=block_id,
                    source_locator=str(getattr(block, "source_locator", "")),
                    evidence_text=text,
                    match_type=match_type,
                ))
    return tuple(candidates)


def freeze_confirmed_candidates(candidates: Iterable[NormativeCandidate], confirmed_ids: Iterable[str]) -> tuple[dict, ...]:
    selected = set(str(item) for item in confirmed_ids)
    return tuple({
        "candidate_id": item.candidate_id, "value": item.value,
        "source_block_id": item.source_block_id, "source_locator": item.source_locator,
        "evidence_text": item.evidence_text, "match_type": item.match_type,
        "confirmed": item.candidate_id in selected,
    } for item in candidates if item.candidate_id in selected)
