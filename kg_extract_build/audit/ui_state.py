"""Streamlit 审核页面使用的纯状态投影，便于 AppTest/单元测试验证。"""

from __future__ import annotations


def execution_summary(report: dict) -> dict[str, int]:
    tasks = report.get("tasks", [])
    return {
        "已完成": sum(item.get("execution_status") == "completed" for item in tasks),
        "系统失败": sum(item.get("execution_status") == "failed" for item in tasks),
        "未执行": sum(item.get("execution_status") == "pending" for item in tasks),
        "人工复核/降级": sum(item.get("result_status") == "manual_review" for item in tasks),
    }


def split_evidence(evidence: list[dict]) -> dict[str, list[dict]]:
    groups = {"document": [], "normative_clause": [], "graph_clue": []}
    for item in evidence:
        kind = item.get("evidence_type", "document")
        groups.setdefault(kind, []).append(item)
    return groups


def pending_review_task_ids(report: dict) -> list[str]:
    return [
        str(task.get("task_id"))
        for task in report.get("tasks", [])
        if task.get("manual_reviews") and task.get("human_review_status") != "resolved"
    ]


def publish_gate(report: dict) -> dict[str, object]:
    pending = pending_review_task_ids(report)
    return {"can_publish": not pending, "pending_task_ids": pending, "message": "可以发布正式报告" if not pending else "仍有人工必办项未处置"}


def version_summary(versions: list[dict]) -> list[dict]:
    return [{
        "报告 ID": item.get("report_id", ""), "状态": item.get("status", ""),
        "版本": item.get("version", ""), "创建者": item.get("generated_by") or "—",
        "创建时间": str(item.get("created_at") or "—"),
    } for item in versions]
