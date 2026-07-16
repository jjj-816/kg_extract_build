from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


TripletKey = tuple[str, str, str, str, str]
CanonicalTripletKey = tuple[str, str, str]
TRIPLET_FIELDS = ("head", "head_type", "relation", "tail", "tail_type")


@dataclass(frozen=True)
class GoldAnnotations:
    root: Path
    documents: dict[str, list[TripletKey]] = field(default_factory=dict)
    canonical_entities: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    canonical_triplets: dict[str, list[CanonicalTripletKey]] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def triplet_count(self) -> int:
        return sum(len(items) for items in self.documents.values())


def normalize_triplet(item: Mapping[str, object], schema=None) -> TripletKey | None:
    values = {
        "head": str(item.get("head_name") or item.get("head", "")).strip(),
        "head_type": str(item.get("head_type", "")).strip(),
        "relation": str(item.get("relation", "")).strip(),
        "tail": str(item.get("tail_name") or item.get("tail", "")).strip(),
        "tail_type": str(item.get("tail_type", "")).strip(),
    }
    if not values["head"] or not values["relation"] or not values["tail"]:
        return None
    if schema is not None:
        values["head_type"] = schema.normalize_entity_type(values["head_type"])
        values["tail_type"] = schema.normalize_entity_type(values["tail_type"])
        values["relation"] = schema.normalize_relation(values["relation"])
        if not values["relation"]:
            return None
    return (
        values["head"],
        values["head_type"],
        values["relation"],
        values["tail"],
        values["tail_type"],
    )


def _extract_triplet_items(payload: object) -> tuple[list[Mapping[str, object]], str | None]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)], None
    if not isinstance(payload, Mapping):
        return [], "?? JSON ??????????"
    if "triplets" not in payload:
        return [], "?? JSON ???? triplets ??"
    triplets = payload["triplets"]
    if not isinstance(triplets, list):
        return [], "?? JSON ? triplets ???????"
    return [item for item in triplets if isinstance(item, Mapping)], None


def _document_name(payload: object, file_path: Path) -> str:
    if isinstance(payload, Mapping):
        document = payload.get("document")
        if isinstance(document, Mapping):
            title = str(document.get("title", "")).strip()
            if title:
                return title
    return file_path.parent.name


def _normalization_key(value: object) -> str:
    """Stable lexical key for canonical-name, alias, and mention lookup."""
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", value)


def _document_match_pairs(
    model_documents: set[str], gold_documents: set[str],
) -> list[tuple[str, str]]:
    """Match exact document names first, then unique preprocessing-name variants."""
    pairs = [(name, name) for name in sorted(model_documents & gold_documents)]
    used_model = {model for model, _gold in pairs}
    used_gold = {gold for _model, gold in pairs}

    def key(name: str) -> str:
        value = _normalization_key(name)
        return re.sub(r"[_-]*(?:\u5f85\u8bc4\u4f30|\u9884\u5904\u7406)$", "", value)

    model_by_key: dict[str, list[str]] = {}
    gold_by_key: dict[str, list[str]] = {}
    for name in model_documents - used_model:
        model_by_key.setdefault(key(name), []).append(name)
    for name in gold_documents - used_gold:
        gold_by_key.setdefault(key(name), []).append(name)
    for normalized in sorted(model_by_key.keys() & gold_by_key.keys()):
        models = model_by_key[normalized]
        golds = gold_by_key[normalized]
        if len(models) == len(golds) == 1:
            pairs.append((models[0], golds[0]))
    return sorted(pairs)


def _extract_canonical_entities(payload: object, schema=None) -> list[dict[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    entities = payload.get("canonical_entities", [])
    mentions = payload.get("entity_mentions", [])
    if not isinstance(entities, list):
        return []
    mentions_by_id: dict[str, list[str]] = {}
    if isinstance(mentions, list):
        for mention in mentions:
            if not isinstance(mention, Mapping):
                continue
            entity_id = str(mention.get("canonical_id", "")).strip()
            text = str(mention.get("mention", "")).strip()
            if entity_id and text:
                mentions_by_id.setdefault(entity_id, []).append(text)
    result = []
    for entity in entities:
        if not isinstance(entity, Mapping):
            continue
        entity_id = str(entity.get("entity_id", "")).strip()
        canonical_name = str(entity.get("canonical_name", "")).strip()
        entity_type = str(entity.get("type", "")).strip()
        if schema is not None:
            entity_type = schema.normalize_entity_type(entity_type)
        if not entity_id or not canonical_name:
            continue
        aliases = entity.get("aliases", [])
        aliases = aliases if isinstance(aliases, list) else []
        names = [canonical_name, *aliases, *mentions_by_id.get(entity_id, [])]
        result.append({
            "canonical_id": entity_id,
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "names": [str(name).strip() for name in names if str(name).strip()],
        })
    return result


def _extract_canonical_triplets(payload: object, schema=None) -> list[CanonicalTripletKey]:
    items, _ = _extract_triplet_items(payload)
    result = []
    for item in items:
        head_id = str(item.get("head_id", "")).strip()
        tail_id = str(item.get("tail_id", "")).strip()
        relation = str(item.get("relation", "")).strip()
        if schema is not None:
            relation = schema.normalize_relation(relation)
        if head_id and relation and tail_id:
            result.append((head_id, relation, tail_id))
    return result


def load_gold_annotations(root: Path, schema=None) -> GoldAnnotations:
    root = Path(root).expanduser().resolve()
    documents: dict[str, list[TripletKey]] = {}
    canonical_entities: dict[str, list[dict[str, object]]] = {}
    canonical_triplets: dict[str, list[CanonicalTripletKey]] = {}
    errors: list[dict[str, str]] = []
    if not root.exists():
        return GoldAnnotations(root=root, errors=[{"path": str(root), "error": "???????"}])
    file_paths = [root] if root.is_file() else sorted(root.rglob("*.json"))
    for file_path in file_paths:
        if file_path.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"path": str(file_path), "error": str(exc)})
            continue
        items, parse_error = _extract_triplet_items(payload)
        if parse_error:
            errors.append({"path": str(file_path), "error": parse_error})
            continue
        doc_name = _document_name(payload, file_path)
        triplets = [triplet for item in items if (triplet := normalize_triplet(item, schema=schema)) is not None]
        if triplets:
            documents.setdefault(doc_name, []).extend(triplets)
        canonical = _extract_canonical_entities(payload, schema=schema)
        if canonical:
            canonical_entities.setdefault(doc_name, []).extend(canonical)
        normalized_triplets = _extract_canonical_triplets(payload, schema=schema)
        if normalized_triplets:
            canonical_triplets.setdefault(doc_name, []).extend(normalized_triplets)
    return GoldAnnotations(
        root=root,
        documents=documents,
        canonical_entities=canonical_entities,
        canonical_triplets=canonical_triplets,
        errors=errors,
    )


def compute_gold_hash(root: Path) -> str:
    root = Path(root).expanduser().resolve()
    digest = hashlib.sha256()
    if not root.exists():
        digest.update(str(root).encode("utf-8"))
        return digest.hexdigest()
    if root.is_file():
        digest.update(root.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(root.read_bytes())
        return digest.hexdigest()
    for file_path in sorted(root.rglob("*.json")):
        relative = file_path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class MetricValue:
    name: str
    value: float
    numerator: float | None = None
    denominator: float | None = None
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoreBreakdown:
    precision: float
    recall: float
    f1: float
    true_positive: int
    false_positive: int
    false_negative: int
    tp_items: list[tuple]
    fp_items: list[tuple]
    fn_items: list[tuple]


@dataclass(frozen=True)
class EvaluationResult:
    overall: dict[str, MetricValue]
    by_document: dict[str, dict[str, MetricValue]]
    matched_documents: list[str]
    missing_gold_documents: list[str]
    extra_gold_documents: list[str]
    entity_alignments: list[dict[str, object]] = field(default_factory=list)


def compute_prf(model_items: set[tuple], gold_items: set[tuple]) -> ScoreBreakdown:
    tp = model_items & gold_items
    fp = model_items - gold_items
    fn = gold_items - model_items
    if not model_items and not gold_items:
        precision = recall = f1 = 1.0
    else:
        precision = len(tp) / len(model_items) if model_items else 1.0
        recall = len(tp) / len(gold_items) if gold_items else 1.0
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return ScoreBreakdown(
        precision=precision,
        recall=recall,
        f1=f1,
        true_positive=len(tp),
        false_positive=len(fp),
        false_negative=len(fn),
        tp_items=sorted(tp),
        fp_items=sorted(fp),
        fn_items=sorted(fn),
    )


def _entities(triplets: list[TripletKey]) -> set[tuple[str, str]]:
    values: set[tuple[str, str]] = set()
    for head, head_type, _relation, tail, tail_type in triplets:
        values.add((head, head_type))
        values.add((tail, tail_type))
    return values


def _relations(triplets: list[TripletKey]) -> set[tuple[str, str, str]]:
    return {
        (head, relation, tail)
        for head, _head_type, relation, tail, _tail_type in triplets
    }


def _metric_group(prefix: str, score: ScoreBreakdown) -> dict[str, MetricValue]:
    return {
        f"{prefix}_precision": MetricValue(
            f"{prefix}_precision",
            score.precision,
            score.true_positive,
            score.true_positive + score.false_positive,
            {"fp": score.fp_items[:20]},
        ),
        f"{prefix}_recall": MetricValue(
            f"{prefix}_recall",
            score.recall,
            score.true_positive,
            score.true_positive + score.false_negative,
            {"fn": score.fn_items[:20]},
        ),
        f"{prefix}_f1": MetricValue(
            f"{prefix}_f1",
            score.f1,
            None,
            None,
            {
                "tp": score.true_positive,
                "fp": score.false_positive,
                "fn": score.false_negative,
            },
        ),
    }


def _coverage_counts(
    triplets: list[TripletKey],
    evidence_map: dict[TripletKey, list[str]],
) -> tuple[int, int, list[TripletKey]]:
    covered = 0
    unsupported: list[TripletKey] = []
    for triplet in triplets:
        tail = triplet[3]
        evidence_text = "\n".join(evidence_map.get(triplet, []))
        if tail and tail in evidence_text:
            covered += 1
        else:
            unsupported.append(triplet)
    return covered, len(triplets), unsupported


def _invalid_count(triplets: list[TripletKey], schema) -> tuple[int, list[TripletKey]]:
    if schema is None:
        return 0, []
    invalid: list[TripletKey] = []
    for head, head_type, relation, tail, tail_type in triplets:
        if not schema.is_relation_allowed(relation, head_type, tail_type):
            invalid.append((head, head_type, relation, tail, tail_type))
    return len(invalid), invalid


def _rate_metric(
    name: str,
    numerator: int,
    denominator: int,
    details: dict[str, object] | None = None,
) -> MetricValue:
    value = 0.0 if denominator == 0 else numerator / denominator
    return MetricValue(
        name=name,
        value=value,
        numerator=numerator,
        denominator=denominator,
        details=details or {},
    )


def _canonical_lookup(canonical_entities: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    lookup: dict[str, list[dict[str, object]]] = {}
    for entity in canonical_entities:
        for name in entity.get("names", []):
            key = _normalization_key(name)
            if key and all(
                candidate["canonical_id"] != entity["canonical_id"]
                for candidate in lookup.get(key, [])
            ):
                lookup.setdefault(key, []).append(entity)
    return lookup


def _align_entity(
    name: str,
    entity_type: str,
    lookup: dict[str, list[dict[str, object]]],
    document: str,
) -> dict[str, object]:
    candidates = lookup.get(_normalization_key(name), [])
    same_type = [item for item in candidates if item.get("entity_type") == entity_type]
    if len(same_type) == 1:
        candidate = same_type[0]
        status = "matched_type"
    elif len(candidates) == 1:
        candidate = candidates[0]
        status = "matched_name_type_mismatch"
    elif candidates:
        candidate = None
        status = "ambiguous"
    else:
        candidate = None
        status = "unmapped"
    return {
        "document": document,
        "entity_name": name,
        "entity_type": entity_type,
        "canonical_id": None if candidate is None else candidate["canonical_id"],
        "canonical_name": None if candidate is None else candidate["canonical_name"],
        "canonical_type": None if candidate is None else candidate["entity_type"],
        "match_status": status,
        "candidate_count": len(candidates),
    }


def _canonical_triplet_score(
    model_triplets: list[TripletKey],
    gold_triplets: list[CanonicalTripletKey],
    canonical_entities: list[dict[str, object]],
    document: str,
) -> tuple[ScoreBreakdown, list[dict[str, object]]]:
    lookup = _canonical_lookup(canonical_entities)
    alignments: dict[tuple[str, str], dict[str, object]] = {}

    def align(name: str, entity_type: str) -> dict[str, object]:
        key = (name, entity_type)
        if key not in alignments:
            alignments[key] = _align_entity(name, entity_type, lookup, document)
        return alignments[key]

    predicted: set[CanonicalTripletKey] = set()
    for head, head_type, relation, tail, tail_type in model_triplets:
        head_alignment = align(head, head_type)
        tail_alignment = align(tail, tail_type)
        if head_alignment["canonical_id"] and tail_alignment["canonical_id"]:
            predicted.add((head_alignment["canonical_id"], relation, tail_alignment["canonical_id"]))

    return compute_prf(predicted, set(gold_triplets)), list(alignments.values())


def evaluate_documents(
    model: dict[str, list[TripletKey]],
    gold: dict[str, list[TripletKey]],
    documents: dict[str, str],
    evidence: dict[str, dict[TripletKey, list[str]]],
    schema=None,
    canonical_entities: dict[str, list[dict[str, object]]] | None = None,
    canonical_gold_triplets: dict[str, list[CanonicalTripletKey]] | None = None,
    head_entities: dict[str, list[tuple[str, str]]] | None = None,
) -> EvaluationResult:
    model_docs = set(model)
    gold_docs = set(gold)
    pairs = _document_match_pairs(model_docs, gold_docs)
    matched = [model_doc for model_doc, _gold_doc in pairs]
    matched_model_docs = set(matched)
    matched_gold_docs = {gold_doc for _model_doc, gold_doc in pairs}
    missing_gold = sorted(model_docs - matched_model_docs)
    extra_gold = sorted(gold_docs - matched_gold_docs)

    model_all = [
        triplet
        for model_doc, _gold_doc in pairs
        for triplet in model.get(model_doc, [])
    ]
    gold_all = [
        triplet
        for _model_doc, gold_doc in pairs
        for triplet in gold.get(gold_doc, [])
    ]

    overall: dict[str, MetricValue] = {}
    overall.update(_metric_group("entity", compute_prf(set(_entities(model_all)), set(_entities(gold_all)))))
    overall.update(_metric_group("relation", compute_prf(set(_relations(model_all)), set(_relations(gold_all)))))
    overall.update(_metric_group("triplet", compute_prf(set(model_all), set(gold_all))))

    canonical_entities = canonical_entities or {}
    canonical_gold_triplets = canonical_gold_triplets or {}
    head_entities = head_entities or {}
    canonical_model: set[CanonicalTripletKey] = set()
    canonical_gold: set[CanonicalTripletKey] = set()
    entity_alignments: list[dict[str, object]] = []
    conditional_model: set[TripletKey] = set()
    conditional_gold: set[TripletKey] = set()
    conditional_canonical_model: set[CanonicalTripletKey] = set()
    conditional_canonical_gold: set[CanonicalTripletKey] = set()
    aligned_head_total = 0
    nonempty_head_total = 0
    output_head_total = 0
    output_head_outside_aligned: list[tuple[str, str, str]] = []
    empty_head_samples: list[tuple[str, str, str]] = []
    for model_doc, gold_doc in pairs:
        aligned_heads = set(head_entities.get(model_doc, []))
        output_heads = {
            (head, head_type)
            for head, head_type, _relation, _tail, _tail_type in model.get(model_doc, [])
        }
        nonempty_heads = aligned_heads & output_heads
        aligned_head_total += len(aligned_heads)
        nonempty_head_total += len(nonempty_heads)
        output_head_total += len(output_heads)
        output_head_outside_aligned.extend(
            (model_doc, name, entity_type)
            for name, entity_type in sorted(output_heads - aligned_heads)
        )
        empty_head_samples.extend(
            (model_doc, name, entity_type)
            for name, entity_type in sorted(aligned_heads - nonempty_heads)
        )
        conditional_model.update(
            triplet for triplet in model.get(model_doc, [])
            if (triplet[0], triplet[1]) in nonempty_heads
        )
        conditional_gold.update(
            triplet for triplet in gold.get(gold_doc, [])
            if (triplet[0], triplet[1]) in nonempty_heads
        )
        score, doc_alignments = _canonical_triplet_score(
            model.get(model_doc, []), canonical_gold_triplets.get(gold_doc, []), canonical_entities.get(gold_doc, []), model_doc,
        )
        canonical_model.update(score.tp_items)
        canonical_model.update(score.fp_items)
        canonical_gold.update(score.tp_items)
        canonical_gold.update(score.fn_items)
        entity_alignments.extend(doc_alignments)
        canonical_nonempty_heads = {
            item["canonical_id"]
            for item in doc_alignments
            if (item["entity_name"], item["entity_type"]) in nonempty_heads
            and item["canonical_id"]
        }
        doc_canonical_model = set(score.tp_items) | set(score.fp_items)
        doc_canonical_gold = set(score.tp_items) | set(score.fn_items)
        conditional_canonical_model.update(
            item for item in doc_canonical_model
            if item[0] in canonical_nonempty_heads
        )
        conditional_canonical_gold.update(
            item for item in doc_canonical_gold
            if item[0] in canonical_nonempty_heads
        )
    overall.update(_metric_group(
        "canonical_triplet", compute_prf(canonical_model, canonical_gold),
    ))
    mapped_count = sum(1 for item in entity_alignments if item["canonical_id"])
    overall["canonical_entity_mapping_rate"] = _rate_metric(
        "canonical_entity_mapping_rate", mapped_count, len(entity_alignments),
        {"unmapped": [item for item in entity_alignments if not item["canonical_id"]][:20]},
    )
    overall["nonempty_head_entity_rate"] = _rate_metric(
        "nonempty_head_entity_rate", nonempty_head_total, aligned_head_total,
        {"empty_head_samples": empty_head_samples[:20]},
    )
    overall["empty_head_entity_rate"] = _rate_metric(
        "empty_head_entity_rate", aligned_head_total - nonempty_head_total, aligned_head_total,
    )
    overall["output_head_outside_aligned_rate"] = _rate_metric(
        "output_head_outside_aligned_rate", len(output_head_outside_aligned), output_head_total,
        {"outside_aligned_samples": output_head_outside_aligned[:20]},
    )
    overall.update(_metric_group(
        "nonempty_head_triplet", compute_prf(conditional_model, conditional_gold),
    ))
    overall.update(_metric_group(
        "nonempty_head_canonical_triplet",
        compute_prf(conditional_canonical_model, conditional_canonical_gold),
    ))

    invalid_total, invalid_items = _invalid_count(model_all, schema)
    overall["invalid_relation_rate"] = _rate_metric(
        "invalid_relation_rate",
        invalid_total,
        len(model_all),
        {"invalid": invalid_items[:20]},
    )

    covered_total = 0
    total_for_coverage = 0
    unsupported_all: list[TripletKey] = []
    for model_doc, _gold_doc in pairs:
        covered, total, unsupported = _coverage_counts(
            model.get(model_doc, []),
            evidence.get(model_doc, {}),
        )
        covered_total += covered
        total_for_coverage += total
        unsupported_all.extend(unsupported)
    overall["selected_evidence_coverage"] = _rate_metric(
        "selected_evidence_coverage",
        covered_total,
        total_for_coverage,
    )
    overall["selected_evidence_tail_absence_rate"] = _rate_metric(
        "selected_evidence_tail_absence_rate",
        len(unsupported_all),
        total_for_coverage,
        {"unsupported": unsupported_all[:20]},
    )

    by_document: dict[str, dict[str, MetricValue]] = {}
    for model_doc, gold_doc in pairs:
        by_document[model_doc] = _metric_group(
            "triplet",
            compute_prf(set(model.get(model_doc, [])), set(gold.get(gold_doc, []))),
        )
        score, _ = _canonical_triplet_score(
            model.get(model_doc, []), canonical_gold_triplets.get(gold_doc, []), canonical_entities.get(gold_doc, []), model_doc,
        )
        by_document[model_doc].update(_metric_group("canonical_triplet", score))

    return EvaluationResult(
        overall=overall,
        by_document=by_document,
        matched_documents=matched,
        missing_gold_documents=missing_gold,
        extra_gold_documents=extra_gold,
        entity_alignments=entity_alignments,
    )


def build_preview(
    model_documents: set[str],
    gold: GoldAnnotations,
    model_triplet_count: int,
    existing_evaluations: list[dict],
) -> dict[str, object]:
    gold_documents = set(gold.documents)
    pairs = _document_match_pairs(model_documents, gold_documents)
    matched = [model_doc for model_doc, _gold_doc in pairs]
    missing_gold = sorted(model_documents - set(matched))
    extra_gold = sorted(gold_documents - {gold_doc for _model_doc, gold_doc in pairs})
    return {
        "model_document_count": len(model_documents),
        "gold_document_count": len(gold_documents),
        "matched_document_count": len(matched),
        "matched_documents": matched,
        "missing_gold_documents": missing_gold,
        "extra_gold_documents": extra_gold,
        "gold_triplet_count": gold.triplet_count,
        "model_triplet_count": model_triplet_count,
        "parse_error_count": len(gold.errors),
        "parse_errors": gold.errors,
        "calculation_blocked": bool(gold.errors or not matched or missing_gold),
        "existing_evaluation_count": len(existing_evaluations),
        "existing_evaluations": existing_evaluations,
    }
