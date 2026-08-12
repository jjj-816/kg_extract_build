"""图增强合理性审核执行器，图线索只能产生工程提示。"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .bounded_graph import GraphRetrievalResult
from .executor import AuditIssueResult, TaskExecutionResult


class ReasonablenessRuntime:
    def __init__(self, model: Callable[..., Mapping[str, Any]] | None = None):
        self.model = model

    def run(self, task, evidence, graph_result: GraphRetrievalResult, run_id: str, normative_search=None):
        evidence = list(evidence)
        trace = [{"step": 1, "stage": "task_input", "status": "started", "input": {"task_id": task.task_id, "evidence_block_ids": [item.get("block_id") for item in evidence]}, "output": {}, "error": None}]
        evidence.extend({
            "evidence_type": "graph_clue",
            "clue_id": clue.clue_id,
            "assertion_id": clue.assertion_id,
            "source_document_id": clue.source_document_id,
            "evidence_sentence": clue.evidence_sentence,
            "summary": clue.summary,
        } for clue in graph_result.clues)
        if graph_result.degraded:
            trace.append({"step": 2, "stage": "graph_retrieval", "status": "failed", "input": {"queries": list(graph_result.queries), "relationship_types": list(graph_result.relationship_types)}, "output": {"raw_hit_count": graph_result.raw_hit_count}, "error": graph_result.diagnostic})
            return TaskExecutionResult(
                task.task_id, task.route, "failed", None, tuple(evidence),
                diagnostics=(graph_result.diagnostic or "图检索服务或字段映射失败",), execution_trace=tuple(trace + [{"step": 3, "stage": "reasonableness_model", "status": "not_called", "input": {}, "output": {"reason": "graph_failure"}, "error": None}]),
            )
        if not graph_result.clues:
            trace.append({"step": 2, "stage": "graph_retrieval", "status": "no_evidence", "input": {"queries": list(graph_result.queries), "relationship_types": list(graph_result.relationship_types)}, "output": {"raw_hit_count": graph_result.raw_hit_count, "accepted_clue_count": 0, "diagnostic": graph_result.diagnostic}, "error": None})
            review = AuditIssueResult("工程合理性风险", task.name + "缺少可用图线索，需专家复核", suggestion=graph_result.diagnostic or "未找到足够历史案例线索", machine_status="manual_review")
            return TaskExecutionResult(task.task_id, task.route, "completed", "manual_review", tuple(evidence), manual_reviews=(review,), diagnostics=(graph_result.diagnostic or "图线索不足",), execution_trace=tuple(trace + [{"step": 3, "stage": "reasonableness_model", "status": "not_called", "input": {}, "output": {"reason": "no_graph_evidence"}, "error": None}]))

        second_search = None
        output = {}
        if self.model:
            trace.append({"step": 3, "stage": "reasonableness_model", "status": "started", "input": {"evidence_count": len(evidence), "graph_clue_count": len(graph_result.clues), "queries": list(graph_result.queries), "relationship_types": list(graph_result.relationship_types)}, "output": {}, "error": None})
            output = dict(self.model(task, tuple(evidence), graph_result, run_id=run_id))
            interaction = getattr(self.model, "last_interaction", None)
            if interaction:
                trace.append({"step": len(trace) + 1, "stage": "reasonableness_model_io", "status": "captured", "input": {"prompt": interaction.get("prompt", {}), "messages": interaction.get("messages", [])}, "output": {"raw_response": interaction.get("raw_response"), "parsed_response": interaction.get("parsed_response")}, "error": None})
            trace.append({"step": 4, "stage": "reasonableness_model", "status": "completed", "input": {}, "output": {"issue_count": len(output.get("issues", [])), "needs_normative_candidates": bool(output.get("needs_normative_candidates"))}, "error": None})
            if output.get("needs_normative_candidates") and normative_search is not None:
                second_search = normative_search(query=output.get("normative_query", task.name), scope=output.get("normative_scope", {}))
                output["normative_candidate_search"] = second_search
        issues = []
        for item in output.get("issues", []):
            issues.append(AuditIssueResult(
                "工程合理性风险", str(item.get("summary", "工程合理性提示")),
                suggestion=item.get("suggestion"), actual_value=item.get("actual_value"), expected_value=item.get("expected_value"), machine_status="advisory",
            ))
        if not issues:
            issues.append(AuditIssueResult("工程合理性风险", "图线索支持工程合理性提示，需结合当前方案人工复核", suggestion="图线索不构成规范不符合结论", machine_status="advisory"))
        diagnostics = [f"graph_clue_count={len(graph_result.clues)}"]
        if second_search is not None:
            diagnostics.append("规范候选二次检索=1")
        trace.append({"step": len(trace) + 1, "stage": "task_result", "status": "completed", "input": {}, "output": {"result_status": "manual_review", "issue_count": len(issues)}, "error": None})
        return TaskExecutionResult(task.task_id, task.route, "completed", "manual_review", tuple(evidence), manual_reviews=tuple(issues), diagnostics=tuple(diagnostics), execution_trace=tuple(trace))
