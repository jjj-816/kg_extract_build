"""按 Word 正文真实顺序生成稳定的审核证据块。"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from .models import AuditDocumentBlock, ParsedAuditDocument, StoredAuditDocument


_HEADING_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百]+章|[一二三四五六七八九十]+、|\d+(?:\.\d+){0,3})\s*.+"
)
_NORMALIZE_RE = re.compile(r"[\s\u3000，,。；;：:（）()【】\[\]《》<>‘’'\"、·—-]+")


def normalize_for_match(value: str) -> str:
    return _NORMALIZE_RE.sub("", unicodedata.normalize("NFKC", value or "")).lower()


def iter_body_blocks(document: DocxDocument) -> Iterable[Paragraph | Table]:
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _paragraph_image_refs(paragraph: Paragraph) -> tuple[str, ...]:
    refs: list[str] = []
    for run in paragraph.runs:
        for blip in run._element.xpath(".//*[local-name()='blip']"):
            relationship_id = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
            if relationship_id and relationship_id not in refs:
                refs.append(relationship_id)
    return tuple(refs)


def _table_payload(table: Table) -> tuple[dict, tuple[str, ...]]:
    rows: list[list[str]] = []
    image_refs: list[str] = []
    for row in table.rows:
        row_values: list[str] = []
        for cell in row.cells:
            row_values.append("\n".join(p.text.strip() for p in cell.paragraphs).strip())
            for paragraph in cell.paragraphs:
                for ref in _paragraph_image_refs(paragraph):
                    if ref not in image_refs:
                        image_refs.append(ref)
        rows.append(row_values)
    return {"rows": rows}, tuple(image_refs)


def _is_heading(paragraph: Paragraph, text: str) -> bool:
    style_name = getattr(paragraph.style, "name", "") or ""
    return style_name.lower().startswith("heading") or bool(_HEADING_RE.match(text))


def _next_section_path(current: tuple[str, ...], heading: str) -> tuple[str, ...]:
    normalized = normalize_for_match(heading)
    if normalized.startswith("第") and "章" in normalized:
        return (heading,)
    if re.match(r"^\d+\.\d+", normalized):
        return (*current, heading) if current else (heading,)
    return (*current, heading) if current else (heading,)


def parse_docx_document(
    document: StoredAuditDocument,
    docx_path: str | Path | None = None,
) -> ParsedAuditDocument:
    path = Path(docx_path or document.converted_path or document.original_path).resolve()
    if path.suffix.lower() != ".docx":
        raise ValueError("Word 解析器只接受 .docx 文件")
    doc = Document(str(path))
    blocks: list[AuditDocumentBlock] = []
    section_path: tuple[str, ...] = ()
    paragraph_count = 0
    table_count = 0
    image_count = 0
    for ordinal, item in enumerate(iter_body_blocks(doc), start=1):
        if isinstance(item, Paragraph):
            paragraph_count += 1
            text = item.text.strip()
            if text and _is_heading(item, text):
                section_path = _next_section_path(section_path, text)
            image_refs = _paragraph_image_refs(item)
            image_count += len(image_refs)
            if not text and not image_refs:
                continue
            blocks.append(
                AuditDocumentBlock(
                    block_id=f"{document.document_id}-B{ordinal:04d}",
                    document_id=document.document_id,
                    ordinal=ordinal,
                    block_type="heading" if text and _is_heading(item, text) else "paragraph",
                    section_path=section_path,
                    source_locator=f"word/body[{ordinal}]/paragraph",
                    raw_text=text,
                    normalized_text=normalize_for_match(text),
                    image_refs=image_refs,
                )
            )
            continue
        table_count += 1
        payload, image_refs = _table_payload(item)
        image_count += len(image_refs)
        raw_text = "\n".join(" | ".join(row) for row in payload["rows"] if any(row)).strip()
        blocks.append(
            AuditDocumentBlock(
                block_id=f"{document.document_id}-B{ordinal:04d}",
                document_id=document.document_id,
                ordinal=ordinal,
                block_type="table",
                section_path=section_path,
                source_locator=f"word/body[{ordinal}]/table[{table_count}]",
                raw_text=raw_text,
                normalized_text=normalize_for_match(raw_text),
                table_json=payload,
                image_refs=image_refs,
            )
        )
    first_blocks = blocks[:3]
    visible_text = "".join(block.raw_text for block in first_blocks)
    cover_visual_only = bool(first_blocks and any(block.image_refs for block in first_blocks) and len(visible_text) < 20)
    return ParsedAuditDocument(
        document=document,
        blocks=tuple(blocks),
        paragraph_count=paragraph_count,
        table_count=table_count,
        image_count=image_count,
        cover_visual_only=cover_visual_only,
    )
