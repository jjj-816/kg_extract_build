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
