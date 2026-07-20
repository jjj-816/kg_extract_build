from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class RelationBatch:
    entity_names: tuple[str, ...]
    evidence: tuple[dict, ...]
    entity_evidence_ids: dict[str, tuple[int, ...]]
    context_chars: int


def overlap_coefficient(left_ids: Iterable[int], right_ids: Iterable[int]) -> float:
    left = set(left_ids)
    right = set(right_ids)
    denominator = min(len(left), len(right))
    if denominator == 0:
        return 0.0
    return len(left & right) / denominator


def _normalize_hits(hits: Sequence[Mapping]) -> dict[int, dict]:
    normalized = {}
    for hit in hits:
        sentence_index = int(hit["sentence_index"])
        current = normalized.get(sentence_index)
        candidate = dict(hit)
        if current is None or float(candidate.get("score", 0.0)) > float(
            current.get("score", 0.0)
        ):
            normalized[sentence_index] = candidate
    return normalized


def _make_batch(
    entity_names: Sequence[str],
    normalized: Mapping[str, Mapping[int, dict]],
    deduplicate_evidence: bool = True,
) -> RelationBatch:
    evidence_by_id = {}
    evidence_rows = []
    entity_evidence_ids = {}
    for entity_name in entity_names:
        ids = tuple(sorted(normalized[entity_name]))
        entity_evidence_ids[entity_name] = ids
        for sentence_index in ids:
            candidate = dict(normalized[entity_name][sentence_index])
            if deduplicate_evidence:
                evidence_by_id.setdefault(sentence_index, candidate)
            else:
                evidence_rows.append(candidate)
    evidence = tuple(evidence_by_id[index] for index in sorted(evidence_by_id)) if deduplicate_evidence else tuple(evidence_rows)
    return RelationBatch(
        entity_names=tuple(entity_names),
        evidence=evidence,
        entity_evidence_ids=entity_evidence_ids,
        context_chars=sum(
            len(str(item.get("sentence", ""))) for item in evidence
        ),
    )


def build_relation_batches(
    entity_evidence: Mapping[str, Sequence[Mapping]],
    *,
    max_entities: int,
    min_overlap: float,
    max_context_chars: int,
    deduplicate_evidence: bool = True,
) -> list[RelationBatch]:
    if max_entities < 1:
        raise ValueError("每批实体数必须至少为 1")
    if not 0.0 <= min_overlap <= 1.0:
        raise ValueError("上下文重叠阈值必须在 0 到 1 之间")
    if max_context_chars < 1:
        raise ValueError("批次上下文字符上限必须为正数")

    normalized = {
        entity_name: _normalize_hits(hits)
        for entity_name, hits in entity_evidence.items()
    }
    remaining = list(normalized)
    batches = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        for candidate in tuple(remaining):
            if len(group) >= max_entities:
                break
            candidate_ids = normalized[candidate].keys()
            if not all(
                overlap_coefficient(
                    candidate_ids,
                    normalized[member].keys(),
                )
                >= min_overlap
                for member in group
            ):
                continue
            proposed = _make_batch([*group, candidate], normalized, deduplicate_evidence)
            if proposed.context_chars > max_context_chars:
                continue
            group.append(candidate)
            remaining.remove(candidate)
        batches.append(_make_batch(group, normalized, deduplicate_evidence))
    return batches


def build_fixed_relation_batches(
    entity_evidence: Mapping[str, Sequence[Mapping]],
    *,
    max_entities: int,
    max_context_chars: int,
    deduplicate_evidence: bool = True,
) -> list[RelationBatch]:
    """Build sequential fixed-size batches without evidence-overlap grouping.

    Context is still deduplicated by sentence id inside each batch so the same
    sentence is not repeated in a single LLM prompt.
    """
    if max_entities < 1:
        raise ValueError("每批实体数必须至少为 1")
    if max_context_chars < 1:
        raise ValueError("批次上下文字符上限必须为正数")

    normalized = {
        entity_name: _normalize_hits(hits)
        for entity_name, hits in entity_evidence.items()
    }
    names = list(normalized)
    batches = []
    index = 0
    while index < len(names):
        group = []
        while index < len(names) and len(group) < max_entities:
            candidate = names[index]
            proposed = _make_batch([*group, candidate], normalized, deduplicate_evidence)
            # Preserve input order and never use overlap to select members.
            # A single oversized entity is retained rather than discarded.
            if group and proposed.context_chars > max_context_chars:
                break
            group.append(candidate)
            index += 1
        batches.append(_make_batch(group, normalized, deduplicate_evidence))
    return batches
