"""规范合规语义审核的受控执行器。"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .executor import AuditIssueResult, TaskExecutionResult
from .normative_scope import NormativeScopePreflight
from .semantic_compliance import select_published_clause_evidence, validate_compliance_conclusion


class ComplianceRuntime:
    def __init__(self, normative_search: Callable[..., Mapping[str, Any]], model: Callable[..., Mapping[str, Any]], planner=None):
        self.normative_search = normative_search
        self.model = model
        self.planner = planner

    def run(self, task, evidence, *, scope_preflight: NormativeScopePreflight, run_id: str) -> TaskExecutionResult:
        document_evidence = tuple(dict(item, evidence_type="document") for item in evidence)
        if scope_preflight.blocked:
            review = AuditIssueResult("规范库覆盖缺口", f"{task.name}无法启动合规结论", suggestion="；".join(scope_preflight.blocking_reasons), machine_status="manual_review")
            return TaskExecutionResult(task.task_id, task.route, "completed", "manual_review", document_evidence, manual_reviews=(review,), diagnostics=scope_preflight.blocking_reasons)
        plan = self.planner.plan(task, tuple(evidence)) if self.planner is not None else None
        query = "\n".join(plan.normative_queries) if plan and plan.normative_queries else "\n".join(item.get("raw_text", "") for item in evidence)
        search_result = self.normative_search(query=query, scope=scope_preflight.scope)
        normative_evidence = select_published_clause_evidence(search_result, scope_preflight.scope)
        if not normative_evidence:
            review = AuditIssueResult("规范库覆盖缺口", f"{task.name}未获得可用规范条款", suggestion="不得将检索缺失解释为符合", machine_status="manual_review")
            return TaskExecutionResult(task.task_id, task.route, "completed", "manual_review", document_evidence, manual_reviews=(review,), diagnostics=("规范检索未返回可用条款",))
        package = {"run_id": run_id, "task_id": task.task_id, "document_evidence": document_evidence, "normative_evidence": normative_evidence}
        try:
            output = validate_compliance_conclusion(self.model(task, package), {item["block_id"] for item in document_evidence}, normative_evidence)
        except (ValueError, TypeError, KeyError) as exc:
            return TaskExecutionResult(task.task_id, task.route, "failed", None, document_evidence + normative_evidence, diagnostics=(f"合规结论校验失败：{exc}",))
        issues = tuple(AuditIssueResult(**item) for item in output.get("issues", []))
        plan_diagnostics = tuple(plan.diagnostics) if plan else ()
        return TaskExecutionResult(task.task_id, task.route, "completed", output["result_status"], document_evidence + normative_evidence, issues=issues, diagnostics=(f"normative_clause_count={len(normative_evidence)}", *plan_diagnostics))
