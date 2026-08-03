"""加载并校验已发布的固定审核任务库。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .models import AuditTaskDefinition
from .settings import AUDIT_TASK_LIBRARY_PATH


class TaskLibraryError(ValueError):
    """任务库不是可用于正式审核的已发布版本。"""


@dataclass(frozen=True)
class PublishedTaskLibrary:
    task_library_id: str
    version: str
    sha256: str
    source_path: Path
    tasks: tuple[AuditTaskDefinition, ...]

    def task_by_id(self, task_id: str) -> AuditTaskDefinition:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        raise KeyError(f"任务库中不存在任务：{task_id}")


def _task_from_record(record: dict) -> AuditTaskDefinition:
    return AuditTaskDefinition(
        task_id=str(record["task_id"]),
        order=int(record["order"]),
        section=str(record["section"]),
        name=str(record["name"]),
        task_type=str(record["type"]),
        route=str(record["route"]),
        fallback_route=record.get("fallback_route"),
        input_unit=str(record["input_unit"]),
        locators=tuple(str(value) for value in record.get("locators", [])),
        required=tuple(str(value) for value in record.get("required", [])),
        checks=tuple(str(value) for value in record.get("checks", [])),
        evidence_roles=tuple(str(value) for value in record.get("evidence_roles", [])),
        issue_categories=tuple(str(value) for value in record.get("issue_categories", [])),
        completion_stage=str(record["completion_stage"]),
        work_type_scope=str(record["work_type_scope"]),
    )


def load_published_task_library(path: str | Path | None = None) -> PublishedTaskLibrary:
    source_path = Path(path or AUDIT_TASK_LIBRARY_PATH).expanduser().resolve()
    if not source_path.is_file():
        raise TaskLibraryError(f"审核任务库文件不存在：{source_path}")
    raw_bytes = source_path.read_bytes()
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskLibraryError(f"审核任务库不是有效 UTF-8 JSON：{source_path}") from exc
    if data.get("status") != "published":
        raise TaskLibraryError("正式审核只能加载状态为 published 的任务库")
    if data.get("base_library"):
        base_path = (source_path.parent / data["base_library"]).resolve()
        base_data = json.loads(base_path.read_text(encoding="utf-8"))
        task_records = list(base_data["tasks"])
        updates = data.get("task_updates", {})
        task_records = [{**record, **updates.get(record["task_id"], {})} for record in task_records]
        task_records.extend(data.get("additional_tasks", []))
    else:
        task_records = data.get("tasks")
    if not isinstance(task_records, list) or not task_records:
        raise TaskLibraryError("审核任务库缺少 tasks")
    tasks = tuple(_task_from_record(item) for item in task_records)
    task_ids = [task.task_id for task in tasks]
    orders = [task.order for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise TaskLibraryError("审核任务库存在重复 task_id")
    if len(orders) != len(set(orders)):
        raise TaskLibraryError("审核任务库存在重复 order")
    return PublishedTaskLibrary(
        task_library_id=str(data["task_library_id"]),
        version=str(data["version"]),
        sha256=hashlib.sha256(raw_bytes).hexdigest().upper(),
        source_path=source_path,
        tasks=tuple(sorted(tasks, key=lambda item: item.order)),
    )
