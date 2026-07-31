"""审核阶段 0/1 的稳定领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StoredAuditDocument:
    document_id: str
    original_filename: str
    file_type: str
    content_hash: str
    original_path: Path
    created_at: str
    converted_path: Path | None = None
    converted_hash: str | None = None
    converter_name: str | None = None
    converter_version: str | None = None
    conversion_status: str = "not_required"
    conversion_diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditImage:
    image_id: str
    document_id: str
    relationship_id: str
    source_part: str
    source_locator: str
    content_type: str
    file_extension: str
    content_hash: str
    stored_path: Path
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class AuditDocumentBlock:
    block_id: str
    document_id: str
    ordinal: int
    block_type: str
    section_path: tuple[str, ...]
    source_locator: str
    raw_text: str
    normalized_text: str
    table_json: dict[str, Any] | None = None
    image_refs: tuple[str, ...] = ()
    parse_status: str = "parsed"

    def to_record(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "document_id": self.document_id,
            "ordinal": self.ordinal,
            "block_type": self.block_type,
            "section_path": list(self.section_path),
            "source_locator": self.source_locator,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "table_json": self.table_json,
            "image_refs": list(self.image_refs),
            "parse_status": self.parse_status,
        }


@dataclass(frozen=True)
class ParsedAuditDocument:
    document: StoredAuditDocument
    blocks: tuple[AuditDocumentBlock, ...]
    paragraph_count: int
    table_count: int
    image_count: int
    cover_visual_only: bool
    images: tuple[AuditImage, ...] = ()


@dataclass(frozen=True)
class AuditTaskDefinition:
    task_id: str
    order: int
    section: str
    name: str
    task_type: str
    route: str
    fallback_route: str | None
    input_unit: str
    locators: tuple[str, ...]
    required: tuple[str, ...]
    checks: tuple[str, ...]
    evidence_roles: tuple[str, ...]
    issue_categories: tuple[str, ...]
    completion_stage: str
    work_type_scope: str


@dataclass(frozen=True)
class TaskLocationHit:
    block_id: str
    source_locator: str
    section_path: tuple[str, ...]
    matched_locators: tuple[str, ...]
    score: float


@dataclass(frozen=True)
class TaskLocationResult:
    task_id: str
    status: str
    hits: tuple[TaskLocationHit, ...] = ()
    diagnostic: str | None = None


@dataclass(frozen=True)
class TaskBinding:
    task_id: str
    locator_profile: str
    handler_key: str
