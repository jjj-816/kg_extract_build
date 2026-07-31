"""基于已发布任务库的只读证据定位器。"""

from __future__ import annotations

from .models import AuditDocumentBlock, AuditTaskDefinition, TaskBinding, TaskLocationHit, TaskLocationResult
from .word_parser import normalize_for_match


def locate_task(
    task: AuditTaskDefinition,
    blocks: tuple[AuditDocumentBlock, ...] | list[AuditDocumentBlock],
    binding: TaskBinding | None = None,
) -> TaskLocationResult:
    """按任务绑定选择定位策略；多个证据块属于同一任务证据组时不视为歧义。"""
    profile = binding.locator_profile if binding else "generic_locator"
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
    if profile == "ordered_steps":
        # 施工顺序通常由标题、连续段落和表格共同组成；保留标题后的相邻块作为同一证据组。
        anchors = {item.block_id for item in matches.values()}
        for index, block in enumerate(blocks):
            if block.block_id not in anchors:
                continue
            for nearby in blocks[index + 1 : index + 4]:
                if block.section_path and nearby.section_path and nearby.section_path != block.section_path:
                    break
                matches.setdefault(nearby.block_id, TaskLocationHit(
                    block_id=nearby.block_id, source_locator=nearby.source_locator,
                    section_path=nearby.section_path, matched_locators=("施工顺序上下文",), score=0.60,
                ))
    hits = tuple(sorted(matches.values(), key=lambda item: (-item.score, item.block_id)))
    if not hits:
        return TaskLocationResult(
            task_id=task.task_id,
            status="not_located",
            diagnostic="未在已解析的段落或表格中定位到任务锚点",
        )
    return TaskLocationResult(
        task_id=task.task_id,
        status="located",
        hits=hits,
        diagnostic=(
            None if len(hits) == 1
            else f"定位配置 {profile} 已形成 1 组任务证据，共 {len(hits)} 个证据块"
        ),
    )


def locate_all_tasks(
    tasks: tuple[AuditTaskDefinition, ...],
    blocks: tuple[AuditDocumentBlock, ...],
    bindings: dict[str, TaskBinding] | None = None,
) -> dict[str, TaskLocationResult]:
    return {task.task_id: locate_task(task, blocks, (bindings or {}).get(task.task_id)) for task in tasks}
