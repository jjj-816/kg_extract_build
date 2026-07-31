"""阶段 1 的上传、解析和任务定位编排。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .bindings import build_task_bindings
from .document_store import store_uploaded_word
from .locator import locate_all_tasks
from .models import ParsedAuditDocument, TaskBinding, TaskLocationResult
from .task_library import PublishedTaskLibrary, load_published_task_library
from .word_converter import convert_doc_to_docx
from .word_parser import parse_docx_document


@dataclass(frozen=True)
class AuditPreview:
    parsed_document: ParsedAuditDocument
    task_library: PublishedTaskLibrary
    bindings: dict[str, TaskBinding]
    locations: dict[str, TaskLocationResult]

    def task_rows(self) -> list[dict[str, object]]:
        rows = []
        for task in self.task_library.tasks:
            location = self.locations[task.task_id]
            rows.append(
                {
                    "任务 ID": task.task_id,
                    "章节": task.section,
                    "任务": task.name,
                    "路由": task.route,
                    "定位状态": location.status,
                    "候选证据数": len(location.hits),
                    "定位说明": location.diagnostic or "",
                }
            )
        return rows


def create_audit_preview(
    filename: str,
    content: bytes,
    storage_dir: str | Path | None = None,
    task_library_path: str | Path | None = None,
) -> AuditPreview:
    library = load_published_task_library(task_library_path)
    document = store_uploaded_word(filename, content, storage_dir=storage_dir)
    if document.file_type == "doc":
        converted_path = convert_doc_to_docx(
            document.original_path,
            document.original_path.parents[1] / "converted",
        )
        document = type(document)(
            document_id=document.document_id,
            original_filename=document.original_filename,
            file_type=document.file_type,
            content_hash=document.content_hash,
            original_path=document.original_path,
            created_at=document.created_at,
            converted_path=converted_path,
        )
    parsed_document = parse_docx_document(document)
    bindings = build_task_bindings(library)
    locations = locate_all_tasks(library.tasks, parsed_document.blocks)
    return AuditPreview(parsed_document, library, bindings, locations)
