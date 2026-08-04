"""第三章设备计划与附录 D 的宽松覆盖、数量比较。"""

from __future__ import annotations

import re


def normalize_name(value: str) -> str:
    value = re.sub(r"[\s（）()【】\[\]、,，]", "", value or "")
    return re.sub(r"(?:工器具|等)$", "", value)


def _records(evidence, appendix: bool) -> list[tuple[str, str, str]]:
    records = []
    for item in evidence:
        section = " / ".join(item["section_path"])
        if ("附录D" in section.replace(" ", "")) != appendix:
            continue
        rows = ((item.get("table_json") or {}).get("rows") or [])
        if len(rows) < 2:
            continue
        header = [str(v) for v in rows[0]]
        name = next((i for i, v in enumerate(header) if "名称" in v), None)
        quantity = next((i for i, v in enumerate(header) if "数量" in v), None)
        if name is None: continue
        for row in rows[1:]:
            value = str(row[name]).strip() if name < len(row) else ""
            if value:
                records.append((normalize_name(value), value, str(row[quantity]).strip() if quantity is not None and quantity < len(row) else ""))
    return records


def compare_coverage(evidence) -> tuple[tuple[str, ...], tuple[tuple[str, str, str], ...]]:
    plans, appendix = _records(evidence, False), _records(evidence, True)
    missing, mismatches = [], []
    for norm, name, count in plans:
        matched = [(raw, quantity) for other, raw, quantity in appendix if norm == other or norm in other or other in norm]
        # “常用工具（锄头、铲子等）”可由附录 D 的明确拆分成员覆盖；“等”不产生新成员。
        members = [normalize_name(item) for item in re.findall(r"[（(]([^）)]+)[）)]", name) for item in re.split(r"[、，,]", item) if item and item != "等"]
        if not matched and members and all(any(member == other or member in other for other, _, _ in appendix) for member in members):
            matched = [("拆分工具", "")]
        if not matched:
            missing.append(name); continue
        if len(matched) == 1 and count and matched[0][1] and count != matched[0][1]:
            mismatches.append((name, count, matched[0][1]))
    return tuple(missing), tuple(mismatches)
