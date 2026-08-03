"""阶段 1 的区域约束式证据定位，仅返回原文位置而不作审核结论。"""

from __future__ import annotations

from collections import defaultdict
import re

from .models import AuditDocumentBlock, AuditTaskDefinition, TaskBinding, TaskEvidenceGroup, TaskLocationHit, TaskLocationResult
from .word_parser import normalize_for_match

_REGIONS = {
    "COVER": ("封面", "第一章"), "DOC": (), "BASIS": ("第一章", "编制依据", "文件依据"),
    "OVERVIEW": ("第二章", "工程概况"), "PREP": ("第三章", "施工准备", "资源配置"),
    "ARR": ("第四章", "施工安排", "施工顺序"), "HSE": ("第五章", "健康安全环保", "应急"),
    "APPA": ("附录a",), "APPB": ("附录b",), "APPC": ("附录c",), "APPD": ("附录d",), "APPE": ("附录e",),
}
_WEAK = {"施工方案", "工序", "控制措施", "→"}
_PROFILE_TARGETS = {
    "BASIS-003": "1.2其他依据",
    "ARR-003": "4.4.1施工重难点",
    "ARR-004": "4.4.2施工组织机构及技术措施",
    "ARR-005": "4.4.2施工组织机构及技术措施",
    "HSE-001": "5.1", "HSE-002": "5.1", "HSE-003": "5.2",
}


def _family(task: AuditTaskDefinition) -> str:
    return task.task_id.split("-", 1)[0]


def _block_part(block: AuditDocumentBlock) -> str:
    return "body" if block.source_locator.startswith("word/body") else "other"


def _eligible(task: AuditTaskDefinition, block: AuditDocumentBlock) -> bool:
    if block.block_type == "toc_entry" or not block.normalized_text or block.normalized_text.isdigit():
        return False
    if _family(task) == "COVER":
        return _block_part(block) == "body" and block.ordinal <= 12
    return _block_part(block) == "body"


def _region_match(task: AuditTaskDefinition, block: AuditDocumentBlock) -> bool:
    terms = _REGIONS.get(_family(task), ())
    if not terms:
        return True
    source = normalize_for_match(" ".join(block.section_path) + " " + block.raw_text)
    return any(normalize_for_match(term) in source for term in terms)


def _matched(task: AuditTaskDefinition, block: AuditDocumentBlock) -> tuple[str, ...]:
    return tuple(value for value in task.locators if normalize_for_match(value) in block.normalized_text)


def _support(blocks, anchor_index: int, path: tuple[str, ...]) -> tuple[tuple[str, ...], bool]:
    support, chars, truncated = [], 0, False
    for block in blocks[anchor_index:]:
        if block.block_type == "heading" and block is not blocks[anchor_index] and len(block.section_path) <= len(path):
            break
        if path and block.section_path[:len(path)] != path:
            continue
        if len(support) >= 50 or chars + len(block.raw_text) > 6000:
            truncated = True
            break
        support.append(block.block_id)
        chars += len(block.raw_text)
    return tuple(support), truncated


def _anchors(task: AuditTaskDefinition, blocks, profile: str):
    result = []
    for index, block in enumerate(blocks):
        if not _eligible(task, block):
            continue
        matches = _matched(task, block)
        if profile == "ordered_steps":
            strong = ("施工顺序", "施工流程", "工艺流程")
            matches = tuple(dict.fromkeys((*matches, *(term for term in strong if normalize_for_match(term) in block.normalized_text))))
        if not matches and not (block.block_type == "heading" and _region_match(task, block)):
            continue
        if not _region_match(task, block) and not (block.block_type == "heading" and matches):
            continue
        if not matches or all(value in _WEAK for value in matches):
            if block.block_type not in {"heading", "table"}:
                continue
        result.append((index, matches, _region_match(task, block)))
    return result


def _merge_groups(task: AuditTaskDefinition, blocks, anchors, profile: str) -> tuple[TaskEvidenceGroup, ...]:
    merged: dict[tuple[str, ...], list[tuple[int, tuple[str, ...], bool]]] = defaultdict(list)
    for item in anchors:
        path = blocks[item[0]].section_path
        merged[path or (f"block:{blocks[item[0]].block_id}",)].append(item)
    groups = []
    for number, (path, candidates) in enumerate(merged.items(), start=1):
        # 标题优先成为组锚点；其余同章节命中全部并入支持块。
        index, matches, exact = sorted(candidates, key=lambda item: (blocks[item[0]].block_type != "heading", -len(item[1]), item[0]))[0]
        support, truncated = _support(blocks, index, blocks[index].section_path)
        all_matches = tuple(dict.fromkeys(value for _, values, _ in candidates for value in values))
        extra = tuple(blocks[item[0]].block_id for item in candidates if blocks[item[0]].block_id not in support)
        support = tuple(dict.fromkeys((*support, *extra)))
        score = 0.42 + (0.32 if exact else 0.0) + (0.16 if blocks[index].block_type == "heading" else 0.06) + min(0.08, 0.02 * len(all_matches))
        groups.append(TaskEvidenceGroup(
            group_id=f"{task.task_id}-G{number:02d}", anchor_block_id=blocks[index].block_id,
            supporting_block_ids=support, section_path=blocks[index].section_path, matched_locators=all_matches,
            score=round(min(score, 0.99), 3), reason=f"{profile}：按章节边界合并标题、正文、表格和图片引用",
            anchor_type="section_heading" if blocks[index].block_type == "heading" else "table_anchor",
            location_mode="exact_region" if exact else "fallback_location", truncated=truncated,
        ))
    return tuple(groups)


def _cross_group(task, blocks, profile):
    roles = {
        "cross_section_core_work_coverage": (("core_work", ("主要工作量",)), ("work_scope", ("作业内容", "施工范围")), ("sequence", ("施工顺序",))),
        "equipment_material_and_work_items": (("equipment", ("设备", "机具", "工器具")), ("material", ("材料",)), ("work_items", ("主要工作量", "作业内容"))),
    }[profile]
    selected, missing = [], []
    for role, terms in roles:
        candidate = next((i for i, b in enumerate(blocks) if _eligible(task, b) and b.block_type in {"heading", "table"} and any(normalize_for_match(t) in b.normalized_text for t in terms)), None)
        if candidate is None:
            missing.append(role)
        else:
            support, _ = _support(blocks, candidate, blocks[candidate].section_path)
            selected.extend(support)
    if not selected:
        return ()
    anchor = next(block for block in blocks if block.block_id == selected[0])
    return (TaskEvidenceGroup(f"{task.task_id}-G01", anchor.block_id, tuple(dict.fromkeys(selected)), anchor.section_path,
        tuple(term for _, terms in roles for term in terms), 0.86, f"{profile}：按角色收集章节实际内容" + (f"；未定位角色：{','.join(missing)}" if missing else ""), "section_heading", "cross_section", False),)


def _body_blocks(blocks):
    return [block for block in blocks if _block_part(block) == "body"]


def _group(task, selected, reason: str, mode: str, section_path: tuple[str, ...] | None = None) -> TaskEvidenceGroup | None:
    if not selected:
        return None
    ordered = tuple(sorted({block.block_id: block for block in selected}.values(), key=lambda block: block.ordinal))
    anchor = ordered[0]
    return TaskEvidenceGroup(
        f"{task.task_id}-G01", anchor.block_id, tuple(block.block_id for block in ordered),
        section_path if section_path is not None else anchor.section_path, (), 0.99, reason, "section_heading", mode, False,
    )


def _matches(block: AuditDocumentBlock, value: str) -> bool:
    needle = normalize_for_match(value)
    haystack = normalize_for_match(" ".join(block.section_path) + " " + block.raw_text)
    return bool(needle and needle in haystack)


def _section_region(blocks, anchor_index: int):
    """Return only same-body blocks up to the next peer/parent heading."""
    anchor = blocks[anchor_index]
    path = anchor.section_path
    result = []
    for block in blocks[anchor_index:]:
        if _block_part(block) != "body":
            break
        if block is not anchor and block.block_type == "heading" and len(block.section_path) <= len(path):
            break
        if path and block.section_path[:len(path)] != path:
            continue
        result.append(block)
    return result


def _find_section_anchor(blocks, target: str):
    candidates = [index for index, block in enumerate(blocks) if block.block_type == "heading" and _matches(block, target)]
    return candidates[0] if candidates else None


def _appendix_region(task, blocks, appendix: str):
    token = normalize_for_match(f"附录{appendix}")
    candidates = [index for index, block in enumerate(blocks)
                  if _block_part(block) == "body" and block.block_type != "toc_entry"
                  and token in normalize_for_match(block.raw_text)]
    if not candidates:
        return None
    # Lists of appendices occur before the real appendix body.  The physical
    # last occurrence is the actual appendix title/table in normal Word files.
    start = candidates[-1]
    selected = []
    for block in blocks[start:]:
        if _block_part(block) != "body":
            break
        if block is not blocks[start] and block.block_type != "toc_entry" and re.match(r"附录\s*[A-EＡ-Ｅ]", block.raw_text.strip(), re.IGNORECASE):
            break
        selected.append(block)
    return _group(task, selected, f"shared_appendix_{appendix.lower()}：实际附录原文", "appendix_region")


def _special_location(task, blocks, profile: str):
    body = _body_blocks(blocks)
    if profile == "cover_region":
        selected = []
        for block in body[:12]:
            if block.block_type == "heading" and selected:
                break
            selected.append(block)
            if block.image_refs:
                break
        if not any(block.image_refs for block in selected):
            return None
        group = _group(task, selected, "cover_region：正文首页封面，需人工视觉核验", "cover_region", ("封面",))
        return group
    if profile == "toc_region":
        toc = [block for block in body if block.block_type == "toc_entry"]
        return _group(task, toc, "toc_region：目录内容控件中的连续目录条目", "toc_region", ("目录",))
    if profile.startswith("shared_appendix_"):
        return _appendix_region(task, body, profile[-1].upper())
    if profile == "shared_parent_section":
        index = _find_section_anchor(body, "3.1")
        return _group(task, _section_region(body, index) if index is not None else [], "shared_parent_section：完整 3.1 施工准备", "section_region")
    if profile in {"exact_section", "exact_subsection", "shared_subsection", "shared_section"}:
        target = _PROFILE_TARGETS.get(task.task_id, task.section.split("/")[-1])
        index = _find_section_anchor(body, target)
        return _group(task, _section_region(body, index) if index is not None else [], f"{profile}：绑定目标章节", "section_region")
    if profile == "anchored_subregion":
        section_index = _find_section_anchor(body, "5.2")
        if section_index is None:
            return None
        section = _section_region(body, section_index)
        start = next((index for index, block in enumerate(section) if "应急处置" in block.raw_text), None)
        return _group(task, section[start:] if start is not None else [], "anchored_subregion：5.2 应急处置至章节结束", "section_region")
    if profile == "person_qualification_composite":
        personnel = []
        person_index = _find_section_anchor(body, "3.1.1")
        if person_index is not None:
            personnel.extend(_section_region(body, person_index))
        for block in body:
            text = normalize_for_match(block.raw_text)
            if any(term in text for term in ("人员配置", "人员组织", "资格证", "电工")) and not any(term in text for term in ("设备", "材料", "机具")):
                personnel.append(block)
        return _group(task, personnel, "person_qualification_composite：人员组织、人员配置与证件图片", "composite_region")
    return None


def locate_task(task: AuditTaskDefinition, blocks: tuple[AuditDocumentBlock, ...] | list[AuditDocumentBlock], binding: TaskBinding | None = None) -> TaskLocationResult:
    profile = binding.locator_profile if binding else "generic_locator"
    special = _special_location(task, blocks, profile)
    if profile in {"cover_region", "toc_region", "shared_parent_section", "exact_section", "exact_subsection", "shared_subsection", "shared_section", "anchored_subregion", "person_qualification_composite"} or profile.startswith("shared_appendix_"):
        if special is None:
            return TaskLocationResult(task.task_id, "not_located", diagnostic="未在任务绑定的正文证据区域中找到可用原文")
        diagnostic = "已定位封面图片，需人工视觉核验" if profile == "cover_region" else None
        return TaskLocationResult(task.task_id, "located", evidence_groups=(special,),
            hits=(TaskLocationHit(special.anchor_block_id, next(block.source_locator for block in blocks if block.block_id == special.anchor_block_id), special.section_path, (), special.score),), diagnostic=diagnostic)
    groups = _cross_group(task, blocks, profile) if profile in {"cross_section_core_work_coverage", "equipment_material_and_work_items"} else _merge_groups(task, blocks, _anchors(task, blocks, profile), profile)
    if profile == "appendix_e_control_measures":
        groups = tuple(group for group in groups if "附录e" in normalize_for_match(" ".join(group.section_path)))
    if not groups:
        return TaskLocationResult(task.task_id, "not_located", diagnostic="未找到预期区域内的章节或表格锚点；未使用目录、页眉、页脚或全文弱关键词回填")
    ordered = tuple(sorted(groups, key=lambda group: (-group.score, group.group_id)))
    ambiguous = len(ordered) > 1 and ordered[0].score - ordered[1].score < 0.06 and (
        ordered[0].location_mode != "exact_region" or ordered[0].matched_locators == ordered[1].matched_locators
    )
    selected = ordered[:2] if ambiguous else ordered[:1]
    lookup = {block.block_id: block for block in blocks}
    hits = tuple(TaskLocationHit(group.anchor_block_id, lookup[group.anchor_block_id].source_locator, group.section_path, group.matched_locators, group.score) for group in selected)
    return TaskLocationResult(task.task_id, "ambiguous" if ambiguous else "located", hits=hits, evidence_groups=selected,
        diagnostic="多个跨章节回退候选得分接近，请人工选择" if ambiguous else None)


def locate_all_tasks(tasks: tuple[AuditTaskDefinition, ...], blocks: tuple[AuditDocumentBlock, ...], bindings: dict[str, TaskBinding] | None = None) -> dict[str, TaskLocationResult]:
    return {task.task_id: locate_task(task, blocks, (bindings or {}).get(task.task_id)) for task in tasks}
