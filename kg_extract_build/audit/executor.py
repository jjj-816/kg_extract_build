"""阶段 2 审核路由：确定性/线下闭环及未接入能力的显式阻断。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evidence_reader import resolve_group_blocks
from .models import AuditDocumentBlock, AuditTaskDefinition, TaskLocationResult


EXECUTION_STATUSES = frozenset({"pending", "running", "completed", "blocked", "failed"})
RESULT_STATUSES = frozenset({"no_issue", "issue_found", "manual_review", "offline_completion"})


@dataclass(frozen=True)
class AuditIssueResult:
    category: str
    summary: str
    affected_scope: str | None = None
    suggestion: str | None = None
    machine_status: str = "open"


@dataclass(frozen=True)
class TaskExecutionResult:
    task_id: str
    route: str
    execution_status: str
    result_status: str | None
    evidence: tuple[dict[str, Any], ...]
    issues: tuple[AuditIssueResult, ...] = ()
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


def execute_deterministic(task: AuditTaskDefinition, parsed, location: TaskLocationResult) -> TaskExecutionResult:
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
        return TaskExecutionResult(task.task_id, task.route, "completed", "manual_review", evidence, (issue,))
    return TaskExecutionResult(task.task_id, task.route, "completed", "no_issue", evidence)


def execute_offline_completion(task: AuditTaskDefinition, parsed, location: TaskLocationResult) -> TaskExecutionResult:
    evidence = _evidence(parsed, location)
    if not evidence:
        return _missing_evidence_result(task, location)
    issue = AuditIssueResult(
        "待线下完善项", f"{task.name}属于打印后填写、勾选、签字或验收项目。",
        suggestion="请在纸质或受控线下流程中完成并由审核员确认。", machine_status="offline_completion",
    )
    return TaskExecutionResult(task.task_id, task.route, "completed", "offline_completion", evidence, (issue,))


def execute_blocked_route(task: AuditTaskDefinition, parsed, location: TaskLocationResult) -> TaskExecutionResult:
    evidence = _evidence(parsed, location)
    labels = {
        "jsa_rule": "JSA 只读适配器", "semantic_compliance": "规范检索与合规语义审核", "semantic_reasonableness": "图增强合理性审核",
    }
    message = f"{labels.get(task.route, task.route)}尚未接入；该任务未被默认判定为通过。"
    return TaskExecutionResult(task.task_id, task.route, "blocked", None, evidence, diagnostics=(message,))


class AuditOrchestrator:
    """对冻结的阶段一预览逐任务执行，单任务问题不影响其他任务。"""

    def execute_preview(self, preview) -> tuple[TaskExecutionResult, ...]:
        results = []
        for task in preview.task_library.tasks:
            location = preview.locations[task.task_id]
            if task.route == "deterministic":
                result = execute_deterministic(task, preview.parsed_document, location)
            elif task.route == "offline_completion":
                result = execute_offline_completion(task, preview.parsed_document, location)
            else:
                result = execute_blocked_route(task, preview.parsed_document, location)
            self._validate(result)
            results.append(result)
        return tuple(results)

    @staticmethod
    def _validate(result: TaskExecutionResult) -> None:
        if result.execution_status not in EXECUTION_STATUSES:
            raise ValueError(f"非法执行状态：{result.execution_status}")
        if result.result_status is not None and result.result_status not in RESULT_STATUSES:
            raise ValueError(f"非法业务结果：{result.result_status}")
        if result.execution_status == "completed" and result.result_status is None:
            raise ValueError("已完成任务必须具有业务结果")
        if result.execution_status == "blocked" and result.result_status is not None:
            raise ValueError("被阻断任务不能伪造业务结果")
