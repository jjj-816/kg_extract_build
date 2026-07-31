"""基于已发布任务库的只读证据定位器。"""

from __future__ import annotations

from .models import AuditDocumentBlock, AuditTaskDefinition, TaskLocationHit, TaskLocationResult
from .word_parser import normalize_for_match


def locate_task(
    task: AuditTaskDefinition,
    blocks: tuple[AuditDocumentBlock, ...] | list[AuditDocumentBlock],
) -> TaskLocationResult:
    matches: dict[str, TaskLocationHit] = {}
    normalized_section = normalize_for_match(task.section)
    for block in blocks:
        searchable = block.normalized_text
        matched: list[str] = []
        for locator in task.locators:
            normalized_locator = normalize_for_match(locator)
            if normalized_locator and normalized_locator in searchable:
                matched.append(locator)
        if not matched and normalized_section:
            path_text = normalize_for_match(" ".join(block.section_path))
            if normalized_section in path_text:
                matched.append(task.section)
        if not matched:
            continue
        score = min(1.0, 0.65 + min(0.1 * len(matched), 0.3))
        if block.block_type == "heading":
            score = min(1.0, score + 0.05)
        matches[block.block_id] = TaskLocationHit(
            block_id=block.block_id,
            source_locator=block.source_locator,
            section_path=block.section_path,
            matched_locators=tuple(matched),
            score=score,
        )
    hits = tuple(sorted(matches.values(), key=lambda item: (-item.score, item.block_id)))
    if not hits:
        return TaskLocationResult(
            task_id=task.task_id,
            status="not_located",
            diagnostic="未在已解析的段落或表格中定位到任务锚点",
        )
    return TaskLocationResult(
        task_id=task.task_id,
        status="located" if len(hits) == 1 else "multiple_candidates",
        hits=hits,
        diagnostic=None if len(hits) == 1 else "存在多个候选证据块，正式审核前可由定位规则进一步收敛",
    )


def locate_all_tasks(
    tasks: tuple[AuditTaskDefinition, ...],
    blocks: tuple[AuditDocumentBlock, ...],
) -> dict[str, TaskLocationResult]:
    return {task.task_id: locate_task(task, blocks) for task in tasks}
