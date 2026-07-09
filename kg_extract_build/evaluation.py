from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


TripletKey = tuple[str, str, str, str, str]
TRIPLET_FIELDS = ("head", "head_type", "relation", "tail", "tail_type")


@dataclass(frozen=True)
class GoldAnnotations:
    root: Path
    documents: dict[str, list[TripletKey]] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def triplet_count(self) -> int:
        return sum(len(items) for items in self.documents.values())


def normalize_triplet(item: Mapping[str, object], schema=None) -> TripletKey | None:
    values = {
        field: str(item.get(field, "")).strip()
        for field in TRIPLET_FIELDS
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


def _extract_triplet_items(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        triplets = payload.get("triplets", [])
        if isinstance(triplets, list):
            return [item for item in triplets if isinstance(item, Mapping)]
    return []


def load_gold_annotations(root: Path, schema=None) -> GoldAnnotations:
    root = Path(root).expanduser().resolve()
    documents: dict[str, list[TripletKey]] = {}
    errors: list[dict[str, str]] = []
    if not root.exists() or not root.is_dir():
        return GoldAnnotations(
            root=root,
            errors=[{"path": str(root), "error": "标注文件夹不存在"}],
        )

    for file_path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"path": str(file_path), "error": str(exc)})
            continue
        doc_name = file_path.parent.name
        triplets = [
            triplet
            for item in _extract_triplet_items(payload)
            if (triplet := normalize_triplet(item, schema=schema)) is not None
        ]
        if triplets:
            documents.setdefault(doc_name, []).extend(triplets)
    return GoldAnnotations(root=root, documents=documents, errors=errors)


def compute_gold_hash(root: Path) -> str:
    root = Path(root).expanduser().resolve()
    digest = hashlib.sha256()
    if not root.exists() or not root.is_dir():
        digest.update(str(root).encode("utf-8"))
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
    document_text: str,
    evidence_map: dict[TripletKey, list[str]],
) -> tuple[int, int, list[TripletKey]]:
    covered = 0
    unsupported: list[TripletKey] = []
    for triplet in triplets:
        tail = triplet[3]
        evidence_text = "\n".join(evidence_map.get(triplet, []))
        if tail and (tail in evidence_text or tail in document_text):
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


def evaluate_documents(
    model: dict[str, list[TripletKey]],
    gold: dict[str, list[TripletKey]],
    documents: dict[str, str],
    evidence: dict[str, dict[TripletKey, list[str]]],
    schema=None,
) -> EvaluationResult:
    model_docs = set(model)
    gold_docs = set(gold)
    matched = sorted(model_docs & gold_docs)
    missing_gold = sorted(model_docs - gold_docs)
    extra_gold = sorted(gold_docs - model_docs)

    model_all = [
        triplet
        for doc in matched
        for triplet in model.get(doc, [])
    ]
    gold_all = [
        triplet
        for doc in matched
        for triplet in gold.get(doc, [])
    ]

    overall: dict[str, MetricValue] = {}
    overall.update(_metric_group("entity", compute_prf(set(_entities(model_all)), set(_entities(gold_all)))))
    overall.update(_metric_group("relation", compute_prf(set(_relations(model_all)), set(_relations(gold_all)))))
    overall.update(_metric_group("triplet", compute_prf(set(model_all), set(gold_all))))

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
    for doc in matched:
        covered, total, unsupported = _coverage_counts(
            model.get(doc, []),
            documents.get(doc, ""),
            evidence.get(doc, {}),
        )
        covered_total += covered
        total_for_coverage += total
        unsupported_all.extend(unsupported)
    overall["evidence_coverage"] = _rate_metric(
        "evidence_coverage",
        covered_total,
        total_for_coverage,
    )
    overall["hallucination_rate"] = _rate_metric(
        "hallucination_rate",
        len(unsupported_all),
        total_for_coverage,
        {"unsupported": unsupported_all[:20]},
    )

    by_document: dict[str, dict[str, MetricValue]] = {}
    for doc in matched:
        by_document[doc] = _metric_group(
            "triplet",
            compute_prf(set(model.get(doc, [])), set(gold.get(doc, []))),
        )

    return EvaluationResult(
        overall=overall,
        by_document=by_document,
        matched_documents=matched,
        missing_gold_documents=missing_gold,
        extra_gold_documents=extra_gold,
    )


def build_preview(
    model_documents: set[str],
    gold: GoldAnnotations,
    model_triplet_count: int,
    existing_evaluations: list[dict],
) -> dict[str, object]:
    gold_documents = set(gold.documents)
    matched = sorted(model_documents & gold_documents)
    missing_gold = sorted(model_documents - gold_documents)
    extra_gold = sorted(gold_documents - model_documents)
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
        "existing_evaluation_count": len(existing_evaluations),
        "existing_evaluations": existing_evaluations,
    }
