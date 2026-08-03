"""阶段二 JSON 智能审核初稿构造，不生成或修改原 Word。"""

from __future__ import annotations

from collections import Counter


def build_draft_report(preview, results) -> dict:
    result_by_task = {result.task_id: result for result in results}
    status_counts = Counter(result.result_status or result.execution_status for result in results)
    tasks = []
    for task in preview.task_library.tasks:
        result = result_by_task[task.task_id]
        tasks.append({
            "task_id": task.task_id,
            "task_name": task.name,
            "route": task.route,
            "execution_status": result.execution_status,
            "result_status": result.result_status,
            "diagnostics": list(result.diagnostics),
            "issues": [issue.__dict__ for issue in result.issues],
            "manual_reviews": [issue.__dict__ for issue in result.manual_reviews],
            "offline_items": [issue.__dict__ for issue in result.offline_items],
            "advisories": [issue.__dict__ for issue in result.advisories],
            "evidence": list(result.evidence),
        })
    return {
        "report_type": "audit_draft_v1",
        "document": {"filename": preview.parsed_document.document.original_filename, "document_id": preview.parsed_document.document.document_id},
        "task_library": {"id": preview.task_library.task_library_id, "version": preview.task_library.version, "sha256": preview.task_library.sha256},
        "summary": {"task_count": len(tasks), "status_counts": dict(status_counts)},
        "tasks": tasks,
    }
