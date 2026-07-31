"""阶段 1 的任务定位和后续执行器绑定。"""

from __future__ import annotations

from .models import TaskBinding
from .task_library import PublishedTaskLibrary


HANDLER_BY_ROUTE = {
    "deterministic": "deterministic",
    "offline_completion": "offline_completion",
    "jsa_rule": "jsa_rule",
    "semantic_compliance": "semantic_compliance",
    "semantic_reasonableness": "semantic_reasonableness",
}

LOCATOR_PROFILE_BY_TASK = {
    "PREP-007": "cross_section_core_work_coverage",
    "ARR-002": "ordered_steps",
    "APPD-002": "equipment_material_and_work_items",
    "APPE-002": "appendix_e_control_measures",
}


def build_task_bindings(library: PublishedTaskLibrary) -> dict[str, TaskBinding]:
    bindings: dict[str, TaskBinding] = {}
    for task in library.tasks:
        handler = HANDLER_BY_ROUTE.get(task.route)
        if handler is None:
            raise ValueError(f"任务 {task.task_id} 使用未知路由：{task.route}")
        bindings[task.task_id] = TaskBinding(
            task_id=task.task_id,
            locator_profile=LOCATOR_PROFILE_BY_TASK.get(task.task_id, "generic_locator"),
            handler_key=handler,
        )
    return bindings
