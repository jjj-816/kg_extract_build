"""表头、业务行和缺失字段的确定性事实提取。"""

from __future__ import annotations

from .fields import is_meaningful


def column_indexes(header: list[str], fields: tuple[str, ...]) -> dict[str, int | None]:
    return {field: next((index for index, value in enumerate(header) if field in value), None) for field in fields}


def is_appd_business_row(values: list[str], indexes: dict[str, int | None]) -> bool:
    name = values[indexes["名称"]].strip() if indexes.get("名称") is not None and indexes["名称"] < len(values) else ""
    serial = values[indexes["序号"]].strip() if indexes.get("序号") is not None and indexes["序号"] < len(values) else ""
    joined = " ".join(values)
    if not (is_meaningful(name) or is_meaningful(serial)):
        return False
    return not any(token in joined for token in ("说明", "注：", "签字", "盖章", "日期", "示例"))


def appd_missing_fields(evidence) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    required = ("名称", "数量", "完好情况", "综合评价")
    required_columns = ("序号", *required, "规格型号", "入场时间", "验收结果", "验收人")
    missing_columns, missing_values, business_rows = set(), set(), False
    for item in evidence:
        table = item.get("table_json") or {}
        rows = table.get("rows") or []
        if not rows:
            continue
        header = [str(value).strip() for value in rows[0]]
        indexes = column_indexes(header, required_columns)
        missing_columns.update(field for field, index in indexes.items() if index is None)
        if any(indexes.get(field) is None for field in ("序号", "名称")):
            continue
        for row in rows[1:]:
            values = [str(value).strip() for value in row]
            if not is_appd_business_row(values, indexes):
                continue
            business_rows = True
            for field in required:
                index = indexes[field]
                if index is None or index >= len(values) or not is_meaningful(values[index]):
                    missing_values.add(field)
    return tuple(sorted(missing_columns)), tuple(sorted(missing_values)), business_rows


def prep005_missing_fields(evidence) -> tuple[str, ...]:
    missing, found = set(), False
    for item in evidence:
        rows = ((item.get("table_json") or {}).get("rows") or [])
        if not rows:
            continue
        header = [str(value).strip() for value in rows[0]]
        role = next((i for i, value in enumerate(header) if "岗位" in value or "工种" in value), None)
        count = next((i for i, value in enumerate(header) if "人数" in value), None)
        if role is None or count is None:
            continue
        found = True
        for row in rows[1:]:
            values = [str(value).strip() for value in row]
            if not any(is_meaningful(value) for value in values):
                continue
            if role >= len(values) or not is_meaningful(values[role]):
                missing.add("岗位或工种")
            if count >= len(values) or not values[count].isdigit() or int(values[count]) <= 0:
                missing.add("人数")
    return tuple(sorted(missing or ({"人员配置表"} if not found else set())))
