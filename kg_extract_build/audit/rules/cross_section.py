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
