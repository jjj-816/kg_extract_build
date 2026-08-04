"""跨章节归一化与冲突聚合的基础函数。"""

from __future__ import annotations

import re


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").replace("：", ":")


def conflicting_values(values: list[tuple[str, str]]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for value, locator in values:
        if normalize(value):
            grouped.setdefault(normalize(value), []).append(locator)
    return {value: tuple(locators) for value, locators in grouped.items()} if len(grouped) > 1 else {}


def normalize_by_kind(value: str, kind: str) -> str:
    value = normalize(value)
    suffixes = {
        "project_name": ("施工作业方案", "施工方案", "施工"),
        "location": ("平台", "井场", "站场"),
        "organization": ("，", ",", "。"),
    }
    for suffix in suffixes.get(kind, ()):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
    return value


def extract_labeled_values(blocks, labels: tuple[str, ...], kind: str) -> list[tuple[str, str]]:
    """提取跨章节比较值。

    Word 解析后，“2.2 建设地点”常作为标题块，而“长宁 H25A 平台”是同一
    ``section_path`` 下的下一正文块。除“字段名：字段值”外，也要识别这种
    标题—正文分离结构，不能把正文值误判为缺失。
    """
    ordered_blocks = tuple(blocks)
    results = []
    seen = set()

    def append(value: str, locator: str) -> None:
        normalized = normalize_by_kind(value, kind)
        if not normalized:
            return
        item = (normalized, locator)
        if item not in seen:
            seen.add(item)
            results.append(item)

    def section_matches(block, label: str) -> bool:
        target = normalize(label)
        return any(target in normalize(path) for path in getattr(block, "section_path", ()))

    for index, block in enumerate(ordered_blocks):
        text = block.raw_text or ""
        for label in labels:
            match = re.search(re.escape(label) + r"\s*[：:]\s*([^\n|；;]{2,80})", text)
            if match:
                append(match.group(1), block.source_locator)

            # 正文块通常继承标题的 section_path，可直接作为字段值读取。
            if block.block_type != "heading" and section_matches(block, label):
                append(text, block.source_locator)

            # 兼容少数解析器未给正文继承 section_path 的情况：从命中标题后，
            # 读取下一个非标题文本块，直到遇到下一标题。
            if block.block_type == "heading" and label in normalize(text):
                for following in ordered_blocks[index + 1:]:
                    if following.block_type == "heading":
                        break
                    candidate = following.raw_text or ""
                    if candidate.strip():
                        append(candidate, following.source_locator)
                        break
        # 表格中常见“标签｜相邻单元格值”：例如 作业场所｜长宁H2B平台。
        rows = ((getattr(block, "table_json", None) or {}).get("rows") or [])
        for row in rows:
            cells = [str(cell).strip() for cell in row]
            for position, cell in enumerate(cells[:-1]):
                if any(normalize(label) in normalize(cell) for label in labels):
                    append(cells[position + 1], block.source_locator)
    return results
