"""阶段 2 审核路由：确定性/线下闭环及未接入能力的显式阻断。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .evidence_reader import resolve_group_blocks
from .jsa_adapter import JSAAdapterError, audit_jsa
from .models import AuditDocumentBlock, AuditTaskDefinition, TaskLocationResult
from .risk_catalog import RiskCatalogError, detect_work_codes


EXECUTION_STATUSES = frozenset({"pending", "running", "completed", "failed"})
RESULT_STATUSES = frozenset({"no_issue", "issue_found", "manual_review", "offline_completion"})


@dataclass(frozen=True)
class AuditIssueResult:
    category: str
    summary: str
    affected_scope: str | None = None
    suggestion: str | None = None
    actual_value: str | None = None
    expected_value: str | None = None
    candidate_rows: tuple[dict[str, Any], ...] = ()
    candidate_total: int | None = None
    candidate_truncated: bool = False
    machine_status: str = "open"


@dataclass(frozen=True)
class TaskExecutionResult:
    task_id: str
    route: str
    execution_status: str
    result_status: str | None
    evidence: tuple[dict[str, Any], ...]
    issues: tuple[AuditIssueResult, ...] = ()
    manual_reviews: tuple[AuditIssueResult, ...] = ()
    offline_items: tuple[AuditIssueResult, ...] = ()
    advisories: tuple[AuditIssueResult, ...] = ()
    diagnostics: tuple[str, ...] = ()


def _snapshot_block(block: AuditDocumentBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id,
        "block_type": block.block_type,
        "ordinal": block.ordinal,
        "section_path": list(block.section_path),
        "source_locator": block.source_locator,
        "raw_text": block.raw_text,
        "table_json": block.table_json,
        "image_refs": list(block.image_refs),
    }


def _evidence(parsed, location: TaskLocationResult) -> tuple[dict[str, Any], ...]:
    group = location.evidence_groups[0] if location.evidence_groups else None
    return tuple(_snapshot_block(block) for block in resolve_group_blocks(parsed, group))


def _missing_evidence_result(task: AuditTaskDefinition, location: TaskLocationResult) -> TaskExecutionResult:
    message = location.diagnostic or "未找到可供审核的任务证据"
    issue = AuditIssueResult(task.issue_categories[0], f"{task.name}无法核验：{message}", suggestion="请人工确认章节或补充原文。")
    return TaskExecutionResult(task.task_id, task.route, "completed", "issue_found", (), (issue,), (message,))


def _missing_table_values(evidence, required: tuple[str, ...]) -> tuple[str, ...]:
    """Return required headers whose actual business rows contain blanks."""
    missing: set[str] = set()
    for item in evidence:
        payload = item["table_json"] or {}
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        if not rows:
            continue
        header = [str(cell).replace(" ", "") for cell in rows[0]]
        indexes = {field: next((i for i, value in enumerate(header) if field in value), None) for field in required}
        if all(index is None for index in indexes.values()):
            continue
        for row in rows[1:]:
            values = [str(cell).strip() for cell in row]
            if not any(values):
                continue
            for field, index in indexes.items():
                if index is not None and (index >= len(values) or not values[index]):
                    missing.add(field)
    return tuple(sorted(missing))


APPD_VALUE_FIELDS = ("名称", "数量", "完好情况", "综合评价")
APPD_COLUMN_FIELDS = ("名称", "规格型号", "数量", "完好情况", "综合评价", "入场时间", "验收结果", "验收人")
_APPD_NON_BUSINESS_TERMS = ("说明", "注", "备注", "签字", "盖章", "日期", "年", "月", "日", "评估合格", "状态良好", "性能可靠")
_APPD_EXAMPLE_TERMS = ("示例", "样例", "例：", "例:")


def _column_indexes(header: list[str], fields: tuple[str, ...]) -> dict[str, int | None]:
    normalized = [str(cell).replace(" ", "") for cell in header]
    return {field: next((index for index, value in enumerate(normalized) if field in value), None) for field in fields}


def _is_appd_business_row(values: list[str], indexes: dict[str, int | None]) -> bool:
    """附录 D 仅把有效序号或设备名称当作设备业务行。"""
    row_text = " ".join(values)
    if not row_text or any(term in row_text for term in _APPD_EXAMPLE_TERMS):
        return False
    sequence = values[0] if values else ""
    has_sequence = bool(re.fullmatch(r"[0-9０-９]+(?:[.、-][0-9０-９]+)*", sequence.strip()))
    name_index = indexes.get("名称")
    name = values[name_index].strip() if name_index is not None and name_index < len(values) else ""
    is_description = any(term in row_text for term in _APPD_NON_BUSINESS_TERMS)
    has_name = bool(name) and not is_description
    return has_sequence or has_name


def _appd_missing_fields(evidence) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    """返回缺失列、业务行缺失值和是否存在设备业务行。"""
    missing_columns: set[str] = set()
    missing_values: set[str] = set()
    business_row_found = False
    for item in evidence:
        payload = item["table_json"] or {}
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        if not rows:
            continue
        header = [str(cell).strip() for cell in rows[0]]
        indexes = _column_indexes(header, APPD_COLUMN_FIELDS)
        missing_columns.update(field for field, index in indexes.items() if index is None)
        if indexes["名称"] is None:
            continue
        for row in rows[1:]:
            values = [str(cell).strip() for cell in row]
            if not _is_appd_business_row(values, indexes):
                continue
            business_row_found = True
            for field in APPD_VALUE_FIELDS:
                index = indexes[field]
                if index is not None and (index >= len(values) or not values[index]):
                    missing_values.add(field)
    return tuple(sorted(missing_columns)), tuple(sorted(missing_values)), business_row_found


def _has_jsa_business_rows(evidence) -> bool:
    for item in evidence:
        payload = item["table_json"] or {}
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        if len(rows) < 2:
            continue
        header = [str(cell).replace(" ", "") for cell in rows[0]]
        step_index = next((index for index, value in enumerate(header) if "步骤" in value or "作业活动" in value), None)
        hazard_index = next((index for index, value in enumerate(header) if "危害" in value), None)
        if step_index is None or hazard_index is None:
            continue
        for row in rows[1:]:
            values = [str(cell).strip() for cell in row]
            if (step_index < len(values) and values[step_index]) or (hazard_index < len(values) and values[hazard_index]):
                return True
    return False


def _prep005_missing_fields(evidence) -> tuple[str, ...]:
    """PREP-005 accepts either a 岗位 column or a 工种 column for each business row."""
    has_role_column = has_count_column = False
    missing_role_or_trade = missing_count = False
    for item in evidence:
        payload = item["table_json"] or {}
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        if not rows:
            continue
        header = [str(cell).replace(" ", "") for cell in rows[0]]
        role_index = next((i for i, value in enumerate(header) if "岗位" in value), None)
        trade_index = next((i for i, value in enumerate(header) if "工种" in value), None)
        count_index = next((i for i, value in enumerate(header) if "人数" in value), None)
        has_role_column = has_role_column or role_index is not None or trade_index is not None
        has_count_column = has_count_column or count_index is not None
        for row in rows[1:]:
            values = [str(cell).strip() for cell in row]
            if not any(values):
                continue
            role_or_trade = any(index is not None and index < len(values) and values[index] for index in (role_index, trade_index))
            if not role_or_trade:
                missing_role_or_trade = True
            if count_index is not None and (count_index >= len(values) or not values[count_index]):
                missing_count = True
    missing = []
    if not has_role_column or missing_role_or_trade:
        missing.append("岗位或工种")
    if not has_count_column or missing_count:
        missing.append("人数")
    return tuple(missing)


_NO_RISK_WORK_STATEMENT = re.compile(r"(?:无|不涉及).{0,12}(?:风险作业|特殊作业)")


def _arr001_result(task: AuditTaskDefinition, evidence, audit_context: dict | None = None) -> TaskExecutionResult:
    """复核编号填写；目录匹配和人工确认在创建运行前完成。"""
    try:
        detected = (audit_context or {}).get("detected_work_codes")
        detections = detected if detected is not None else [item.as_dict() for item in detect_work_codes(evidence)]
    except RiskCatalogError as exc:
        return TaskExecutionResult(task.task_id, task.route, "failed", None, evidence, diagnostics=(f"风险作业目录配置错误：{exc}",))
    text = "\n".join(item.get("raw_text", "") for item in evidence)
    if not detections:
        if _NO_RISK_WORK_STATEMENT.search(text):
            return TaskExecutionResult(task.task_id, task.route, "completed", "no_issue", evidence)
        issue = AuditIssueResult("信息问题", f"{task.name}未填写编号，也未明确写明无/不涉及风险作业。", suggestion="请填写固定风险作业目录编号，或明确说明无/不涉及风险作业。")
        return TaskExecutionResult(task.task_id, task.route, "completed", "issue_found", evidence, (issue,))
    unmatched_codes = [item["code"] for item in detections if item.get("catalog_match_status") == "unmatched"]
    if unmatched_codes and not (audit_context or {}).get("unmatched_codes_confirmed"):
        review = AuditIssueResult("人工核验项", f"以下编号未匹配固定目录，需人工确认：{'、'.join(unmatched_codes)}", machine_status="manual_review")
        return TaskExecutionResult(task.task_id, task.route, "completed", "manual_review", evidence, manual_reviews=(review,))
    return TaskExecutionResult(task.task_id, task.route, "completed", "no_issue", evidence)


def execute_deterministic(task: AuditTaskDefinition, parsed, location: TaskLocationResult, audit_context: dict | None = None) -> TaskExecutionResult:
    """执行阶段二可判定的存在性、结构和可读性检查。

    任务库中的语义化 ``checks`` 仍由后续语义路由处理；这里不会把
    "定位到原文"扩张解释成规范符合。
    """
    evidence = _evidence(parsed, location)
    if not evidence:
        return _missing_evidence_result(task, location)
    has_content = any(item["raw_text"].strip() or item["table_json"] or item["image_refs"] for item in evidence)
    if not has_content:
        issue = AuditIssueResult(task.issue_categories[0], f"{task.name}定位区域为空", suggestion="请补充可读取的正文、表格或图片。")
        return TaskExecutionResult(task.task_id, task.route, "completed", "issue_found", evidence, (issue,))
    if task.task_id.startswith("COVER-") and parsed.cover_visual_only:
        issue = AuditIssueResult("人工核验项", f"{task.name}包含封面视觉内容，需人工核验。", machine_status="manual_review")
        return TaskExecutionResult(task.task_id, task.route, "completed", "manual_review", evidence, manual_reviews=(issue,))
    if task.task_id == "ARR-001":
        return _arr001_result(task, evidence, audit_context)
    table_requirements = {
        "PREP-004": ("名称", "单位", "数量"),
        "HSE-001": ("步骤", "危害", "风险", "控制"),
        "APPE-001": ("地点", "工程名称", "作业类型", "作业内容"), "APPE-002": ("控制措施",),
    }
    if task.task_id == "APPD-001":
        missing_columns, missing_values, has_business_rows = _appd_missing_fields(evidence)
        if missing_columns:
            issue = AuditIssueResult("信息问题", f"{task.name}缺少固定列：{'、'.join(missing_columns)}", affected_scope="；".join(missing_columns))
            return TaskExecutionResult(task.task_id, task.route, "completed", "issue_found", evidence, (issue,))
        if not has_business_rows:
            issue = AuditIssueResult("信息问题", f"{task.name}未见实际设备业务行", suggestion="请补充非空白、非示例的设备业务数据。")
            return TaskExecutionResult(task.task_id, task.route, "completed", "issue_found", evidence, (issue,))
        if missing_values:
            issue = AuditIssueResult("信息问题", f"{task.name}存在设备业务行字段缺失：{'、'.join(missing_values)}", affected_scope="；".join(missing_values))
            return TaskExecutionResult(task.task_id, task.route, "completed", "issue_found", evidence, (issue,))
        return TaskExecutionResult(task.task_id, task.route, "completed", "no_issue", evidence)
    if task.task_id == "PREP-005":
        missing = _prep005_missing_fields(evidence)
        if missing:
            issue = AuditIssueResult("信息问题", f"{task.name}存在业务行字段缺失：{'、'.join(missing)}", affected_scope="；".join(missing))
            return TaskExecutionResult(task.task_id, task.route, "completed", "issue_found", evidence, (issue,))
        return TaskExecutionResult(task.task_id, task.route, "completed", "no_issue", evidence)
    required = table_requirements.get(task.task_id)
    if required:
        table_text = "\n".join(item["raw_text"] for item in evidence if item["table_json"])
        missing = [field for field in required if field not in table_text]
        if missing:
            issue = AuditIssueResult("信息问题", f"{task.name}缺少核心字段：{'、'.join(missing)}", affected_scope="；".join(missing))
            return TaskExecutionResult(task.task_id, task.route, "completed", "issue_found", evidence, (issue,))
        blank_fields = _missing_table_values(evidence, required)
        if blank_fields and task.task_id in {"PREP-004", "PREP-005", "APPD-001", "APPE-002"}:
            issue = AuditIssueResult("信息问题", f"{task.name}存在业务行字段缺失：{'、'.join(blank_fields)}", affected_scope="；".join(blank_fields))
            return TaskExecutionResult(task.task_id, task.route, "completed", "issue_found", evidence, (issue,))
        if task.task_id in {"PREP-004", "PREP-005", "APPD-001", "APPE-002"} and not any(
            any(any(str(cell).strip() for cell in row) for row in item["table_json"].get("rows", [])[1:])
            for item in evidence if item["table_json"]
        ):
            issue = AuditIssueResult("信息问题", f"{task.name}未见实际业务行", suggestion="请补充非示例的业务数据。")
            return TaskExecutionResult(task.task_id, task.route, "completed", "issue_found", evidence, (issue,))
        if task.task_id == "HSE-001" and not _has_jsa_business_rows(evidence):
            issue = AuditIssueResult("信息问题", f"{task.name}未见可用的 JSA 业务行", suggestion="请至少填写作业步骤或危害信息。")
            return TaskExecutionResult(task.task_id, task.route, "completed", "issue_found", evidence, (issue,))
    if task.task_id == "PREP-006" and any(item["image_refs"] for item in evidence):
        review = AuditIssueResult("人工核验项", "特殊工种资格证明包含图片，需人工核验证件有效期。", machine_status="manual_review")
        return TaskExecutionResult(task.task_id, task.route, "completed", "manual_review", evidence, manual_reviews=(review,))
    return TaskExecutionResult(task.task_id, task.route, "completed", "no_issue", evidence)


def execute_offline_completion(task: AuditTaskDefinition, parsed, location: TaskLocationResult) -> TaskExecutionResult:
    evidence = _evidence(parsed, location)
    if not evidence:
        return _missing_evidence_result(task, location)
    issue = AuditIssueResult(
        "待线下完善项", f"{task.name}属于打印后填写、勾选、签字或验收项目。",
        suggestion="请在纸质或受控线下流程中完成并由审核员确认。", machine_status="offline_completion",
    )
    return TaskExecutionResult(task.task_id, task.route, "completed", "offline_completion", evidence, offline_items=(issue,))


def execute_later_route(task: AuditTaskDefinition, parsed, location: TaskLocationResult) -> TaskExecutionResult:
    evidence = _evidence(parsed, location)
    labels = {
        "jsa_rule": "JSA 只读适配器", "semantic_compliance": "规范检索与合规语义审核", "semantic_reasonableness": "图增强合理性审核",
    }
    message = f"{labels.get(task.route, task.route)}等待后续语义审核；当前未作业务结论。"
    return TaskExecutionResult(task.task_id, task.route, "pending", None, evidence, diagnostics=(message,))


def execute_jsa_advisory(task: AuditTaskDefinition, preview, run_id: str, hse001_result: TaskExecutionResult) -> TaskExecutionResult:
    location = preview.locations[task.task_id]
    evidence = _evidence(preview.parsed_document, location)
    if hse001_result.result_status != "no_issue":
        return TaskExecutionResult(task.task_id, task.route, "completed", "no_issue", evidence, diagnostics=("HSE-001 未通过，未调用 JSA 只读服务。",))
    try:
        response = audit_jsa(preview, run_id)
    except JSAAdapterError as exc:
        return TaskExecutionResult(task.task_id, task.route, "failed", None, evidence, diagnostics=(str(exc),))
    advisories = []
    for item in response.suggestions:
        if item["kind"] == "missing_jsa_step":
            advisories.append(AuditIssueResult(
                "JSA 步骤覆盖建议",
                f"施工顺序步骤“{item.get('step') or '—'}”未在 JSA 表中找到相同或相似步骤。",
                affected_scope=f"步骤：{item.get('step') or '—'}；施工顺序来源：{item.get('source_locator') or '—'}",
                suggestion="请确认该步骤是否适用；如适用，请在 JSA 表中补充该作业步骤后再进行风险辨识。",
                actual_value="JSA 表中未找到相同或相似步骤。",
                expected_value="JSA 应覆盖施工顺序中的适用作业步骤。",
                machine_status="advisory",
            ))
            continue
        if item["kind"] == "missing_hazard_group":
            total = item["total_missing_hazards"]
            returned = item["returned_hazards"]
            suffix = f"，当前展示前 {returned} 条" if item.get("truncated") else ""
            advisories.append(AuditIssueResult(
                "JSA 补充建议",
                f"步骤“{item.get('step') or '—'}”识别到 {total} 条风险库缺失危害候选{suffix}。",
                affected_scope=f"步骤：{item.get('step') or '—'}；来源：{item.get('source_locator') or '—'}",
                suggestion="请结合方案原文和现场条件，确认后将适用候选补充至 JSA。",
                actual_value="当前 JSA 未发现以下候选危害。",
                expected_value=f"风险库候选危害共 {total} 条，本次展示 {returned} 条。",
                candidate_rows=tuple(item["candidates"]), candidate_total=total,
                candidate_truncated=bool(item.get("truncated")), machine_status="advisory",
            ))
            continue
        advisories.append(AuditIssueResult(
            "JSA 补充建议",
            f"{item.get('kind')}：{item.get('basis') or '风险库匹配到补充候选。'}",
            affected_scope=f"步骤：{item.get('step') or '—'}；当前危害/控制措施：{item.get('current_hazard') or item.get('hazard') or '—'} / {item.get('current_control_measure') or '—'}；来源：{item.get('source_locator') or '—'}",
            suggestion=f"候选危害：{item.get('hazard') or '—'}；候选控制措施：{item.get('control_measure') or '—'}；风险等级：{item.get('risk_level') or '—'}。请补充到 JSA 后由人工确认。",
            actual_value=f"危害：{item.get('current_hazard') or item.get('hazard') or '—'}；控制措施：{item.get('current_control_measure') or '—'}",
            expected_value=f"候选危害：{item.get('hazard') or '—'}；候选控制措施：{item.get('control_measure') or '—'}；风险等级：{item.get('risk_level') or '—'}",
            machine_status="advisory",
        ))
    return TaskExecutionResult(task.task_id, task.route, "completed", "no_issue", evidence, advisories=tuple(advisories), diagnostics=response.diagnostics)


def _deprecated_execute_jsa_advisory(task: AuditTaskDefinition, parsed, location: TaskLocationResult) -> TaskExecutionResult:
    evidence = _evidence(parsed, location)
    advisory = AuditIssueResult("JSA 补充建议", "JSA 只读引擎待配置；未生成普通审核问题。", machine_status="advisory")
    return TaskExecutionResult(task.task_id, task.route, "completed", "manual_review", evidence, advisories=(advisory,))


class AuditOrchestrator:
    """对冻结的阶段一预览逐任务执行，单任务问题不影响其他任务。"""

    def execute_preview(self, preview, audit_context: dict | None = None, run_id: str = "preview") -> tuple[TaskExecutionResult, ...]:
        results = []
        result_by_task = {}
        confirmed_work_types = tuple((audit_context or {}).get("confirmed_work_types") or (audit_context or {}).get("work_types", ()))
        for task in preview.task_library.tasks:
            location = preview.locations[task.task_id]
            if task.work_type_scope == "selected" and task.task_id != "ARR-001" and not confirmed_work_types:
                evidence = _evidence(preview.parsed_document, location)
                results.append(TaskExecutionResult(
                    task.task_id, task.route, "pending", None, evidence,
                    diagnostics=("未确认涉及作业类型，该作业类型相关任务暂不启用。",),
                ))
                continue
            if task.route == "deterministic":
                result = execute_deterministic(task, preview.parsed_document, location, audit_context)
            elif task.route == "offline_completion":
                result = execute_offline_completion(task, preview.parsed_document, location)
            elif task.route == "jsa_rule":
                result = execute_jsa_advisory(task, preview, run_id, result_by_task.get("HSE-001"))
            else:
                result = execute_later_route(task, preview.parsed_document, location)
            self._validate(result)
            results.append(result)
            result_by_task[task.task_id] = result
        return tuple(results)

    @staticmethod
    def _validate(result: TaskExecutionResult) -> None:
        if result.execution_status not in EXECUTION_STATUSES:
            raise ValueError(f"非法执行状态：{result.execution_status}")
        if result.result_status is not None and result.result_status not in RESULT_STATUSES:
            raise ValueError(f"非法业务结果：{result.result_status}")
        if result.execution_status == "completed" and result.result_status is None:
            raise ValueError("已完成任务必须具有业务结果")
