"""阶段 1 任务级证据组定位器：只定位，不作合规结论。"""

from __future__ import annotations

from .models import AuditDocumentBlock, AuditTaskDefinition, TaskBinding, TaskEvidenceGroup, TaskLocationHit, TaskLocationResult
from .word_parser import normalize_for_match


def _matched_locators(task: AuditTaskDefinition, block: AuditDocumentBlock) -> tuple[str, ...]:
    text = block.normalized_text
    return tuple(locator for locator in task.locators if normalize_for_match(locator) in text)


def _is_anchor(task: AuditTaskDefinition, block: AuditDocumentBlock) -> tuple[str, ...]:
    matched = _matched_locators(task, block)
    section_match = normalize_for_match(task.section) in normalize_for_match(" ".join(block.section_path))
    # 不再让全篇普通正文仅因关键词出现就成为候选；标题、表格或章节路径才是锚点。
    if matched and block.block_type in {"heading", "table"}:
        return matched
    if matched and any(normalize_for_match(locator) in block.normalized_text[:24] for locator in matched):
        return matched
    if section_match and block.block_type == "heading":
        return matched or (task.section,)
    return ()


def _section_support(blocks: tuple[AuditDocumentBlock, ...] | list[AuditDocumentBlock], anchor_index: int) -> tuple[str, ...]:
    anchor = blocks[anchor_index]
    path, support = anchor.section_path, [anchor.block_id]
    for block in blocks[anchor_index + 1:]:
        if block.block_type == "heading" and path and len(block.section_path) <= len(path):
            break
        if path and block.section_path[:len(path)] != path:
            continue
        support.append(block.block_id)
        if len(support) >= 10:
            break
    return tuple(support)


def _groups_for_anchors(task: AuditTaskDefinition, blocks, anchors: list[tuple[int, tuple[str, ...]]], profile: str) -> tuple[TaskEvidenceGroup, ...]:
    groups = []
    for number, (index, matched) in enumerate(anchors[:4], start=1):
        anchor = blocks[index]
        score = 0.70 + min(len(matched) * 0.08, 0.20) + (0.08 if anchor.block_type == "heading" else 0)
        groups.append(TaskEvidenceGroup(
            group_id=f"{task.task_id}-G{number:02d}", anchor_block_id=anchor.block_id,
            supporting_block_ids=_section_support(blocks, index), section_path=anchor.section_path,
            matched_locators=matched, score=min(score, 1.0),
            reason=f"{profile}：以章节或表格锚点为中心收集连续证据块",
        ))
    return tuple(groups)


def _cross_section_group(task: AuditTaskDefinition, blocks, profile: str) -> tuple[TaskEvidenceGroup, ...]:
    keywords = {
        "cross_section_core_work_coverage": ("主要工作量", "作业内容", "施工顺序"),
        "equipment_material_and_work_items": ("设备", "材料", "机具", "主要工作量", "作业内容"),
    }[profile]
    selected = []
    for block in blocks:
        content = block.normalized_text
        if block.block_type in {"heading", "table"} and any(normalize_for_match(word) in content for word in keywords):
            selected.append(block)
    if not selected:
        return ()
    anchor = selected[0]
    return (TaskEvidenceGroup(
        group_id=f"{task.task_id}-G01", anchor_block_id=anchor.block_id,
        supporting_block_ids=tuple(item.block_id for item in selected[:12]), section_path=anchor.section_path,
        matched_locators=tuple(word for word in keywords if any(normalize_for_match(word) in item.normalized_text for item in selected)),
        score=min(0.70 + 0.06 * len(selected), 0.96), reason=f"{profile}：联合定位跨章节相关内容",
    ),)


def locate_task(task: AuditTaskDefinition, blocks: tuple[AuditDocumentBlock, ...] | list[AuditDocumentBlock], binding: TaskBinding | None = None) -> TaskLocationResult:
    profile = binding.locator_profile if binding else "generic_locator"
    if profile in {"cross_section_core_work_coverage", "equipment_material_and_work_items"}:
        groups = _cross_section_group(task, blocks, profile)
    else:
        anchors = [(index, match) for index, block in enumerate(blocks) if (match := _is_anchor(task, block))]
        if profile == "appendix_e_control_measures":
            anchors = [(index, match) for index, match in anchors if "附录e" in normalize_for_match(" ".join(blocks[index].section_path) + blocks[index].raw_text)]
        groups = _groups_for_anchors(task, blocks, anchors, profile)
    if not groups:
        return TaskLocationResult(task.task_id, "not_located", diagnostic="未找到章节标题、表格标题或强锚点，无法形成任务证据组")
    ordered = tuple(sorted(groups, key=lambda item: (-item.score, item.group_id)))
    ambiguous = len(ordered) > 1 and ordered[0].score - ordered[1].score < 0.10
    hits = tuple(TaskLocationHit(
        block_id=group.anchor_block_id,
        source_locator=next(block.source_locator for block in blocks if block.block_id == group.anchor_block_id),
        section_path=group.section_path, matched_locators=group.matched_locators, score=group.score,
    ) for group in ordered)
    return TaskLocationResult(
        task.task_id, "ambiguous" if ambiguous else "located", hits=hits, evidence_groups=ordered,
        diagnostic=("存在多个接近的章节证据组，请人工选择" if ambiguous else None),
    )


def locate_all_tasks(tasks: tuple[AuditTaskDefinition, ...], blocks: tuple[AuditDocumentBlock, ...], bindings: dict[str, TaskBinding] | None = None) -> dict[str, TaskLocationResult]:
    return {task.task_id: locate_task(task, blocks, (bindings or {}).get(task.task_id)) for task in tasks}
