"""任务证据阅读器的数据整理与 CSV 导出，不依赖 Streamlit。"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .models import AuditDocumentBlock, ParsedAuditDocument, TaskEvidenceGroup


STATUS_LABELS = {"located": "已定位", "ambiguous": "存在多个候选", "not_located": "未定位"}
EXPORT_COLUMNS = ["文档名称", "任务 ID", "任务名称", "预期章节", "定位状态", "系统首选章节", "首选证据原文", "图片数量", "其他候选章节", "来源位置", "人工判断", "备注"]


def task_option_label(task) -> str:
    return f"{task.task_id}｜{task.name}"


def location_status_label(status: str) -> str:
    return STATUS_LABELS.get(status, "未定位")


def group_section_label(group: TaskEvidenceGroup | None) -> str:
    return " / ".join(group.section_path) if group and group.section_path else ""


def resolve_group_blocks(parsed: ParsedAuditDocument, group: TaskEvidenceGroup | None) -> list[AuditDocumentBlock]:
    if group is None:
        return []
    block_map = {block.block_id: block for block in parsed.blocks}
    block_ids = dict.fromkeys((group.anchor_block_id, *group.supporting_block_ids))
    return sorted((block_map[item] for item in block_ids if item in block_map), key=lambda block: block.ordinal)


def readable_source(block: AuditDocumentBlock) -> str:
    part = "正文" if block.source_locator.startswith("word/body") else "页眉/页脚"
    type_label = {"heading": "标题", "paragraph": "段落", "table": "表格", "toc_entry": "目录"}.get(block.block_type, "内容")
    return f"{part}第 {block.ordinal} 个解析位置 · {type_label}"


def block_text_for_export(block: AuditDocumentBlock) -> str:
    if block.block_type == "table" and block.table_json:
        rows = block.table_json.get("rows", [])
        content = "\n".join(" | ".join(str(cell) for cell in row) for row in rows)
    else:
        content = block.raw_text
    if block.image_refs:
        content = (content + "\n" if content else "") + "\n".join("[图片]" for _ in block.image_refs)
    return content


def build_task_evidence_export(preview) -> pd.DataFrame:
    records = []
    for task in preview.task_library.tasks:
        location = preview.locations[task.task_id]
        groups = location.evidence_groups
        primary = groups[0] if groups else None
        blocks = resolve_group_blocks(preview.parsed_document, primary)
        records.append({
            "文档名称": preview.parsed_document.document.original_filename,
            "任务 ID": task.task_id,
            "任务名称": task.name,
            "预期章节": task.section,
            "定位状态": location_status_label(location.status),
            "系统首选章节": group_section_label(primary),
            "首选证据原文": "\n\n".join(block_text_for_export(block) for block in blocks),
            "图片数量": sum(len(block.image_refs) for block in blocks),
            "其他候选章节": "；".join(group_section_label(group) for group in groups[1:]),
            "来源位置": "；".join(readable_source(block) for block in blocks),
            "人工判断": "",
            "备注": "",
        })
    return pd.DataFrame(records, columns=EXPORT_COLUMNS)


def safe_export_filename(filename: str) -> str:
    stem = Path(filename).stem
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem) + "_任务证据.csv"
