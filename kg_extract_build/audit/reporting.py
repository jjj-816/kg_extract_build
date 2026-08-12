"""阶段二 JSON 智能审核初稿构造，不生成或修改原 Word。"""

from __future__ import annotations

from collections import Counter

import pandas as pd


RESULT_GROUPS = (
    ("issues", "审核问题"),
    ("manual_reviews", "人工核验项"),
    ("offline_items", "线下审核项"),
    ("advisories", "JSA 提示项"),
    ("system_errors", "系统错误"),
)
STAGE2_RESULT_EXPORT_COLUMNS = ["结果类型", "任务 ID", "任务名称", "问题类别", "问题说明", "实际值", "期望值", "候选总数", "展示序号", "是否截断", "受影响范围", "来源章节", "处理建议"]


def stage2_result_groups(report: dict) -> dict[str, list[dict]]:
    """将报告中的任务输出展平为阶段 2 结果界面可直接使用的分组。"""
    groups = {key: [] for key, _ in RESULT_GROUPS}
    for task in report.get("tasks", []):
        base = {
            "task_id": task["task_id"],
            "task_name": task["task_name"],
            "section": task.get("section"),
            "expected": task.get("expected", []),
            "route": task.get("route"),
            "execution_status": task.get("execution_status"),
            "diagnostics": task.get("diagnostics", []),
            "result_status": task.get("result_status"),
            "evidence": task.get("evidence", []),
            "execution_trace": task.get("execution_trace", []),
        }
        for key in ("issues", "manual_reviews", "offline_items", "advisories"):
            for item in task.get(key, []):
                groups[key].append({**base, **item, "output_type": key})
        if task.get("execution_status") == "failed":
            groups["system_errors"].append({
                **base,
                "output_type": "system_errors",
                "category": "系统错误",
                "summary": "；".join(task.get("diagnostics", [])) or "任务执行失败，未返回诊断信息。",
                "affected_scope": None,
                "suggestion": "请检查任务配置与依赖服务后重试。",
                "machine_status": "failed",
            })
    return groups


def build_stage2_result_export(report: dict) -> pd.DataFrame:
    """构造阶段 2 审核结果 CSV；每一条输出占一行。"""
    labels = dict(RESULT_GROUPS)
    records = []
    for output_type, entries in stage2_result_groups(report).items():
        for item in entries:
            source_sections = []
            for evidence in item.get("evidence", []):
                section = " / ".join(evidence.get("section_path") or [])
                if section and section not in source_sections:
                    source_sections.append(section)
            base = {
                "结果类型": labels[output_type], "任务 ID": item["task_id"], "任务名称": item["task_name"],
                "问题类别": item.get("category") or "", "问题说明": item.get("summary") or "",
                "实际值": item.get("actual_value") or item.get("summary") or "",
                "受影响范围": item.get("affected_scope") or "",
                "来源章节": "；".join(source_sections) or item.get("section") or "",
                "处理建议": item.get("suggestion") or "",
            }
            candidates = item.get("candidate_rows") or []
            if candidates:
                for number, candidate in enumerate(candidates, 1):
                    records.append({
                        **base,
                        "期望值": f"候选危害：{candidate.get('hazard') or '—'}；候选控制措施：{candidate.get('control_measure') or '—'}；风险等级：{candidate.get('risk_level') or '—'}；相似度：{candidate.get('similarity') or '—'}",
                        "候选总数": item.get("candidate_total") or len(candidates), "展示序号": number,
                        "是否截断": "是" if item.get("candidate_truncated") else "否",
                    })
            else:
                records.append({
                    **base, "期望值": item.get("expected_value") or "；".join(item.get("expected") or []),
                    "候选总数": "", "展示序号": "", "是否截断": "",
                })
    return pd.DataFrame(records, columns=STAGE2_RESULT_EXPORT_COLUMNS)


def build_draft_report(preview, results) -> dict:
    result_by_task = {result.task_id: result for result in results}
    status_counts = Counter(result.result_status or result.execution_status for result in results)
    tasks = []
    for task in preview.task_library.tasks:
        result = result_by_task[task.task_id]
        tasks.append({
            "task_id": task.task_id,
            "task_name": task.name,
            "section": task.section,
            "expected": list(task.required or task.checks),
            "route": task.route,
            "execution_status": result.execution_status,
            "result_status": result.result_status,
            "diagnostics": list(result.diagnostics),
            "issues": [issue.__dict__ for issue in result.issues],
            "manual_reviews": [issue.__dict__ for issue in result.manual_reviews],
            "offline_items": [issue.__dict__ for issue in result.offline_items],
            "advisories": [issue.__dict__ for issue in result.advisories],
            "evidence": list(result.evidence),
            "execution_trace": list(result.execution_trace),
        })
    return {
        "report_type": "audit_draft_v1",
        "document": {"filename": preview.parsed_document.document.original_filename, "document_id": preview.parsed_document.document.document_id},
        "task_library": {"id": preview.task_library.task_library_id, "version": preview.task_library.version, "sha256": preview.task_library.sha256},
        "summary": {"task_count": len(tasks), "status_counts": dict(status_counts)},
        "tasks": tasks,
    }


def build_execution_trace_export(report: dict) -> pd.DataFrame:
    rows = []
    for task in report.get("tasks", []):
        if task.get("route") not in {"semantic_compliance", "semantic_reasonableness"}:
            continue
        for entry in task.get("execution_trace", []):
            rows.append({"task_id": task.get("task_id"), "task_name": task.get("task_name"), "route": task.get("route"), **entry})
    return pd.DataFrame(rows, columns=["task_id", "task_name", "route", "step", "stage", "status", "input", "output", "error"])
