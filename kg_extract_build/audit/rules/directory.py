"""目录块覆盖判定。"""

from .fields import missing_labels


def missing_fixed_entries(text: str) -> tuple[str, ...]:
    return missing_labels(text, ("目录", "第一章", "第二章", "第三章", "第四章", "第五章", "附录A", "附录B", "附录C", "附录D", "附录E"))
