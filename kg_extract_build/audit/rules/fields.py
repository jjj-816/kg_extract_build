"""字段和占位符的无状态确定性事实提取。"""

from __future__ import annotations

import re

PLACEHOLDER_RE = re.compile(r"^(?:—|-|/|无|暂无|待填|待补|示例|\s*)$")


def is_meaningful(value: str) -> bool:
    return bool(value and not PLACEHOLDER_RE.match(value.strip()))


def missing_labels(corpus: str, labels: tuple[str, ...]) -> tuple[str, ...]:
    compact = corpus.replace(" ", "")
    return tuple(label for label in labels if label.replace(" ", "") not in compact)
