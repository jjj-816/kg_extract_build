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
    "COVER-001": "cover_region", "COVER-002": "cover_region", "COVER-003": "cover_region",
    "DOC-001": "toc_region",
    "BASIS-003": "exact_section",
    "PREP-001": "shared_parent_section", "PREP-002": "shared_parent_section",
    "PREP-006": "person_qualification_composite",
    "PREP-007": "cross_section_core_work_coverage",
    "ARR-002": "ordered_steps",
    "ARR-003": "exact_subsection", "ARR-004": "shared_subsection", "ARR-005": "shared_subsection",
    "HSE-001": "shared_section", "HSE-002": "shared_section", "HSE-003": "exact_section", "HSE-004": "anchored_subregion",
    "APPD-002": "shared_appendix_d",
}

for _appendix in "ABCDE":
    for _task_number in range(1, 4):
        LOCATOR_PROFILE_BY_TASK.setdefault(f"APP{_appendix}-{_task_number:03d}", f"shared_appendix_{_appendix.lower()}")


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
