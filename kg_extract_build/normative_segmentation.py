"""逻辑条款 → 物理向量片段（按 token 上限分段，加身份前缀，不静默截断）。"""

from __future__ import annotations

from dataclasses import dataclass

from .normative import ClauseDraft, stable_hash


def build_prefix(family_name: str, hierarchy_path: tuple[str, ...], clause_number: str | None) -> str:
    path = "/".join(str(item) for item in hierarchy_path) if hierarchy_path else "正文"
    number = clause_number or ""
    return f"【规范：{family_name} {path}{(' ' + number) if number else ''}】"


@dataclass(frozen=True)
class SegmentDraft:
    segment_index: int
    embedding_text: str
    token_count: int
    text_hash: str


def _count(tokenizer, text: str) -> int:
    return len(tokenizer(text))


def segment_clause(
    clause: ClauseDraft, *,
    family_name: str,
    tokenizer,
    max_tokens: int = 128,
    overlap_tokens: int = 8,
) -> list[SegmentDraft]:
    prefix = build_prefix(family_name, clause.hierarchy_path, clause.clause_number)
    body = clause.raw_text
    full = f"{prefix}\n{body}"
    if _count(tokenizer, full) <= max_tokens:
        return [SegmentDraft(0, full, _count(tokenizer, full), stable_hash({"t": full}))]

    words = body.split()
    segments: list[SegmentDraft] = []
    index = 0
    start = 0
    while start < len(words):
        chunk: list[str] = []
        budget = max_tokens - _count(tokenizer, prefix)
        for word in words[start:]:
            cost = _count(tokenizer, word) + 1
            if chunk and budget - cost < 0:
                break
            chunk.append(word)
            budget -= cost
        if not chunk:
            chunk = words[start:start + 1]
        advance = max(1, len(chunk) - overlap_tokens)
        text = f"{prefix}\n{' '.join(chunk)}"
        segments.append(
            SegmentDraft(index, text, _count(tokenizer, text), stable_hash({"t": text}))
        )
        start += advance
        index += 1
    return segments
