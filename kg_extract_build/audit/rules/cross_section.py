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
    results = []
    for block in blocks:
        text = block.raw_text or ""
        for label in labels:
            match = re.search(re.escape(label) + r"\s*[：:]\s*([^\n|；;]{2,80})", text)
            if match:
                results.append((normalize_by_kind(match.group(1), kind), block.source_locator))
    return results
