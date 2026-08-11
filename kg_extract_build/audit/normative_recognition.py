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


_BOOK_PATTERN = re.compile(r"《[^》]{2,80}》")
_CODE_PATTERN = re.compile(
    r"(?:GB(?:/T)?|JGJ|JTG|DL|SY|Q/SY|NB/T|SH/T)\s*[A-Z]?\s*\d{2,6}(?:[-—]\d{4})?",
    re.I,
)


def recognize_declared_norms(blocks: Iterable[object]) -> tuple[NormativeCandidate, ...]:
    candidates: list[NormativeCandidate] = []
    seen: set[tuple[str, str]] = set()
    for block in blocks:
        text = str(getattr(block, "raw_text", "") or "")
        matches: list[tuple[str, str]] = []
        paired_code_spans: set[tuple[int, int]] = set()
        for book in _BOOK_PATTERN.finditer(text):
            value = book.group(0).strip()
            tail = text[book.end():book.end() + 24]
            prefix = tail.lstrip(" \t:：,，")
            code = _CODE_PATTERN.match(prefix)
            if code:
                code_start = book.end() + len(tail) - len(prefix) + code.start()
                code_end = book.end() + len(tail) - len(prefix) + code.end()
                value = f"{value}{text[code_start:code_end].strip()}"
                paired_code_spans.add((code_start, code_end))
                matches.append((value, "book_title+standard_code"))
            else:
                matches.append((value, "book_title"))
        for code in _CODE_PATTERN.finditer(text):
            if (code.start(), code.end()) not in paired_code_spans:
                matches.append((code.group(0).strip(), "standard_code"))
        for value, match_type in matches:
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
