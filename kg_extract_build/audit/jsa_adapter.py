"""阶段 2 到 JSA 只读服务的 HTTP 适配器。"""

from __future__ import annotations

from dataclasses import dataclass
import re

import requests

from .evidence_reader import resolve_group_blocks, table_rows
from .settings import AUDIT_JSA_SERVICE_URL, AUDIT_JSA_SIMILARITY_THRESHOLD, AUDIT_JSA_TIMEOUT_SECONDS


class JSAAdapterError(RuntimeError):
    """JSA 只读服务不可调用或返回不符合约定。"""


@dataclass(frozen=True)
class JSAAuditResponse:
    engine_version: str
    suggestions: tuple[dict, ...]
    diagnostics: tuple[str, ...]


def _header_indexes(header: list[str]) -> dict[str, int | None]:
    normalized = [cell.replace(" ", "") for cell in header]
    def find(*terms):
        return next((index for index, value in enumerate(normalized) if any(term in value for term in terms)), None)
    return {"type": find("类型"), "step": find("步骤", "作业活动"), "hazard": find("危害"), "risk": find("风险"), "control": find("控制")}


def _value(row: list[str], index: int | None) -> str:
    return row[index].strip() if index is not None and index < len(row) else ""


_RISK_CATALOG_CODE = re.compile(r"\bCN-[A-Z0-9-]+\b", re.IGNORECASE)
_STEP_EXCLUDED_TERMS = ("风险作业目录", "目录编号", "作业编号", "不涉及风险作业")
_STEP_CHAIN_SPLITTER = re.compile(r"\s*(?:→|->|—>|⇒|＞)\s*")
_STEP_LABEL_PREFIX = re.compile(r"^(?:施工顺序安排|施工顺序|施工步骤|作业步骤)\s*[：:]\s*")


def _usable_step(value: str) -> str:
    step = " ".join(value.split())
    if not step or len(step) > 120 or any(term in step for term in _STEP_EXCLUDED_TERMS):
        return ""
    if _RISK_CATALOG_CODE.search(step) or step.rstrip("：:").endswith(("施工顺序", "施工步骤", "作业步骤")):
        return ""
    return step


def _split_construction_steps(value: str) -> tuple[str, ...]:
    """拆分施工顺序链，防止“施工顺序安排：A→B”被作为一个虚假步骤。"""
    text = _STEP_LABEL_PREFIX.sub("", " ".join(value.split()))
    return tuple(step for part in _STEP_CHAIN_SPLITTER.split(text) if (step := _usable_step(part)))


def build_jsa_request(preview, run_id: str) -> dict:
    """只使用阶段 1 已解析的证据块，不二次打开 Word。"""
    step_location = preview.locations["ARR-002"]
    step_blocks = resolve_group_blocks(preview.parsed_document, step_location.evidence_groups[0] if step_location.evidence_groups else None)
    construction_steps, seen_steps = [], set()
    def add_step(value: str, source_locator: str) -> None:
        for step in _split_construction_steps(value):
            if step not in seen_steps:
                seen_steps.add(step)
                construction_steps.append({"step": step, "source_locator": source_locator})
    for block in step_blocks:
        rows = table_rows(block)
        if rows and len(rows) > 1:
            indexes = _header_indexes(rows[0])
            if indexes["step"] is None:
                continue
            for row_number, row in enumerate(rows[1:], 2):
                add_step(_value(row, indexes["step"]), f"{block.source_locator}/row[{row_number}]")
        elif block.raw_text.strip() and block.block_type != "heading":
            for line in block.raw_text.splitlines():
                add_step(line, block.source_locator)
    jsa_location = preview.locations["HSE-001"]
    jsa_blocks = resolve_group_blocks(preview.parsed_document, jsa_location.evidence_groups[0] if jsa_location.evidence_groups else None)
    jsa_rows = []
    for block in jsa_blocks:
        rows = table_rows(block)
        if not rows:
            continue
        indexes = _header_indexes(rows[0])
        for row_number, row in enumerate(rows[1:], 2):
            step, hazard = _value(row, indexes["step"]), _value(row, indexes["hazard"])
            if not step and not hazard:
                continue
            jsa_rows.append({
                "jsa_type": _value(row, indexes["type"]) or "作业活动步骤",
                "step": step, "hazard": hazard, "risk_level": _value(row, indexes["risk"]),
                "control_measure": _value(row, indexes["control"]),
                "source_locator": f"{block.source_locator}/row[{row_number}]",
            })
    return {"run_id": run_id, "construction_steps": construction_steps, "jsa_rows": jsa_rows, "similarity_threshold": AUDIT_JSA_SIMILARITY_THRESHOLD}


def audit_jsa(preview, run_id: str) -> JSAAuditResponse:
    payload = build_jsa_request(preview, run_id)
    try:
        response = requests.post(AUDIT_JSA_SERVICE_URL, json=payload, timeout=AUDIT_JSA_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise JSAAdapterError(f"JSA 服务请求失败：{exc}") from exc
    if response.status_code != 200:
        raise JSAAdapterError(f"JSA 服务返回 HTTP {response.status_code}：{response.text[:300]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise JSAAdapterError("JSA 服务返回的不是 JSON") from exc
    suggestions, diagnostics = body.get("suggestions"), body.get("diagnostics", [])
    if not isinstance(suggestions, list) or not isinstance(diagnostics, list) or not isinstance(body.get("engine_version"), str):
        raise JSAAdapterError("JSA 服务响应结构无效")
    allowed = {"missing_jsa_step", "missing_hazard_group", "missing_control_measure"}
    if any(not isinstance(item, dict) or item.get("kind") not in allowed for item in suggestions):
        raise JSAAdapterError("JSA 服务返回了无效建议类型")
    for item in suggestions:
        if item["kind"] != "missing_hazard_group":
            continue
        candidates = item.get("candidates")
        total, returned = item.get("total_missing_hazards"), item.get("returned_hazards")
        if (not isinstance(candidates, list) or len(candidates) > 8 or not isinstance(total, int)
                or not isinstance(returned, int) or returned != len(candidates) or total < returned
                or any(not isinstance(candidate, dict) for candidate in candidates)):
            raise JSAAdapterError("JSA 服务返回的缺失危害分组无效")
    return JSAAuditResponse(body["engine_version"], tuple(suggestions), tuple(str(item) for item in diagnostics))
