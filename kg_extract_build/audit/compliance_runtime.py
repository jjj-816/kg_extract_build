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
        trace = []
        def record(stage, status, input_data=None, output_data=None, error=None):
            trace.append({"step": len(trace) + 1, "stage": stage, "status": status, "input": input_data or {}, "output": output_data or {}, "error": error})
        record("task_input", "started", {"task_id": task.task_id, "evidence_block_ids": [item.get("block_id") for item in evidence]})
        record("applicability_preflight", "advisory", output_data={"coverage": [dict(item) for item in scope_preflight.coverage], "scope": scope_preflight.display_summary(), "reasons": list(scope_preflight.blocking_reasons)})
        plan = self.planner.plan(task, tuple(evidence)) if self.planner is not None else None
        if plan:
            planner_model = getattr(self.planner, "model", None)
            planner_io = getattr(planner_model, "last_interaction", None)
            record("retrieval_planning", "completed" if not plan.diagnostics else "degraded", {"evidence_block_ids": list(getattr(plan, "document_block_ids", ())), "prompt_version": getattr(plan, "prompt_version", None)}, {"normative_queries": list(plan.normative_queries), "graph_queries": list(getattr(plan, "graph_queries", ())), "relationship_types": list(getattr(plan, "relationship_types", ())), "diagnostics": list(plan.diagnostics), "llm_prompt": planner_io.get("prompt") if planner_io else None, "llm_messages": planner_io.get("messages") if planner_io else None, "llm_raw_response": planner_io.get("raw_response") if planner_io else None, "llm_parsed_response": planner_io.get("parsed_response") if planner_io else None, "correction_raw_response": planner_io.get("correction_raw_response") if planner_io else None, "correction_parsed_response": planner_io.get("correction_parsed_response") if planner_io else None})
        query = "\n".join(plan.normative_queries) if plan and plan.normative_queries else "\n".join(item.get("raw_text", "") for item in evidence)
        record("normative_retrieval", "started", {"query": query})
        search_result = self.normative_search(query=query, scope=scope_preflight.scope)
        normative_evidence = select_published_clause_evidence(search_result, scope_preflight.scope)
        raw_evidence = list(search_result.get("evidence", ()))
        record("normative_retrieval", "completed" if normative_evidence else "no_evidence", {"query": query}, {"candidate_count": len(raw_evidence), "selected_count": len(normative_evidence), "filtered_count": max(0, len(raw_evidence) - len(normative_evidence)), "coverage": search_result.get("coverage", []), "warnings": search_result.get("warnings", []), "retrieval_trace": search_result.get("retrieval_trace", {}), "diagnostic": search_result.get("diagnostic")})
        if not normative_evidence:
            record("compliance_model", "not_called", output_data={"reason": "no_applicable_normative_evidence"})
            review = AuditIssueResult("规范库覆盖缺口", f"{task.name}未获得可用规范条款", suggestion="不得将检索缺失解释为符合", machine_status="manual_review")
            return TaskExecutionResult(task.task_id, task.route, "completed", "manual_review", document_evidence, manual_reviews=(review,), diagnostics=("规范检索未返回可用条款", *(tuple(plan.diagnostics) if plan else ())), execution_trace=tuple(trace))
        package = {"run_id": run_id, "task_id": task.task_id, "document_evidence": document_evidence, "normative_evidence": normative_evidence}
        try:
            record("compliance_model", "started", {"document_evidence_count": len(document_evidence), "normative_evidence_count": len(normative_evidence)})
            raw_output = self.model(task, package)
            interaction = getattr(self.model, "last_interaction", None)
            if interaction:
                record("compliance_model_io", "captured", output_data=interaction)
            output = validate_compliance_conclusion(raw_output, {item["block_id"] for item in document_evidence}, normative_evidence)
            record("compliance_model", "completed", output_data={"result_status": output.get("result_status"), "issue_count": len(output.get("issues", []))})
        except (ValueError, TypeError, KeyError) as exc:
            record("compliance_model", "failed", error=str(exc))
            return TaskExecutionResult(task.task_id, task.route, "failed", None, document_evidence + normative_evidence, diagnostics=(f"合规结论校验失败：{exc}",), execution_trace=tuple(trace))
        issues = tuple(AuditIssueResult(**item) for item in output.get("issues", []))
        plan_diagnostics = tuple(plan.diagnostics) if plan else ()
        record("task_result", "completed", output_data={"result_status": output["result_status"], "issue_count": len(issues)})
        return TaskExecutionResult(task.task_id, task.route, "completed", output["result_status"], document_evidence + normative_evidence, issues=issues, diagnostics=(f"normative_clause_count={len(normative_evidence)}", *plan_diagnostics), execution_trace=tuple(trace))
