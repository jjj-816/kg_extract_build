from __future__ import annotations

import re
from dataclasses import dataclass, field


IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\([^\)]+\)")
URL_RE = re.compile(r"https?://\S+")
SEQUENCE_PREFIX_RE = re.compile(r"^\s*\d{1,3}[.)）]\s*")
IDENTIFIER_RE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]?\d{15,18})(?![A-Za-z0-9])")
DOT_LEADER_RE = re.compile(r"^\s*[^\n]{1,80}\.{4,}\s*\d+\s*$")
BARE_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
NUMBER_WITH_UNIT_RE = re.compile(r"^\d+(?:\.\d+)?\s*(?:%|cm|mm|m|km|kg|t)$", re.IGNORECASE)
DATE_FRAGMENT_RE = re.compile(r"^\d{4}\D\d{1,2}\D(?:\d{1,2}\D)?$")


@dataclass(frozen=True)
class PreprocessResult:
    clean_text: str
    removed_items: list[dict[str, object]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def is_valid_entity_candidate(name: str) -> bool:
    value = str(name).strip()
    if not value:
        return False
    if BARE_NUMBER_RE.fullmatch(value):
        return False
    if NUMBER_WITH_UNIT_RE.fullmatch(value):
        return False
    if DATE_FRAGMENT_RE.fullmatch(value):
        return False
    if URL_RE.fullmatch(value) or IDENTIFIER_RE.fullmatch(value):
        return False
    return True


def preprocess_document(text: str) -> PreprocessResult:
    removed_items: list[dict[str, object]] = []
    image_count = len(IMAGE_MARKDOWN_RE.findall(text))
    text = IMAGE_MARKDOWN_RE.sub("", text)
    text = URL_RE.sub("", text)

    cleaned_lines: list[str] = []
    sequence_count = 0
    identifier_count = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        if DOT_LEADER_RE.match(line):
            removed_items.append({"line": line_number, "reason": "directory_leader"})
            continue
        sequence_match = SEQUENCE_PREFIX_RE.match(line)
        if sequence_match:
            line = line[sequence_match.end():]
            sequence_count += 1
            removed_items.append({"line": line_number, "reason": "sequence_prefix"})
        line, redacted = IDENTIFIER_RE.subn("[REDACTED]", line)
        if redacted:
            identifier_count += redacted
            removed_items.append({"line": line_number, "reason": "identifier"})
        if line.strip():
            cleaned_lines.append(line.rstrip())

    return PreprocessResult(
        clean_text="\n".join(cleaned_lines),
        removed_items=removed_items,
        stats={
            "image_markdown_count": image_count,
            "removed_sequence_line_count": sequence_count,
            "redacted_identifier_count": identifier_count,
        },
    )
