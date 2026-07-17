"""Fixed, reproducible extraction-method profiles for ablation experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MethodProfile:
    method_id: str
    label: str
    description: str
    prompt_version: str
    relation_strategy: str
    enable_entity_alignment: bool
    enable_retrieval: bool
    enable_schema_validation: bool

    def snapshot(self) -> dict[str, object]:
        return asdict(self)


METHOD_PROFILES: dict[str, MethodProfile] = {
    "R2": MethodProfile(
        method_id="R2",
        label="R2 · LLM-Direct",
        description="按切片直接抽取三元组；不进行实体对齐、检索或后置模式校验。",
        prompt_version="direct-v1",
        relation_strategy="llm_direct",
        enable_entity_alignment=False,
        enable_retrieval=False,
        enable_schema_validation=False,
    ),
    "R3": MethodProfile(
        method_id="R3",
        label="R3 · Single-Entity",
        description="实体对齐后逐实体检索与抽取；不使用共享批次和后置模式校验。",
        prompt_version="single-entity-v1",
        relation_strategy="single_entity",
        enable_entity_alignment=True,
        enable_retrieval=True,
        enable_schema_validation=False,
    ),
    "R4": MethodProfile(
        method_id="R4",
        label="R4 · Fixed-Batch",
        description="实体对齐和检索后按固定实体数顺序分批；不按证据重叠分组，也不进行后置模式校验。",
        prompt_version="relation-batch-v1",
        relation_strategy="fixed_batch",
        enable_entity_alignment=True,
        enable_retrieval=True,
        enable_schema_validation=False,
    ),
    "R5": MethodProfile(
        method_id="R5",
        label="R5 · Shared-Context-Batch",
        description="实体对齐和检索后，按共享证据构建上下文批次；不进行后置模式校验。",
        prompt_version="relation-batch-v1",
        relation_strategy="shared_context_batch",
        enable_entity_alignment=True,
        enable_retrieval=True,
        enable_schema_validation=False,
    ),
    "R6": MethodProfile(
        method_id="R6",
        label="R6 · Full Method",
        description="完整方法：实体对齐、检索、共享上下文批量抽取和后置模式校验。",
        prompt_version="relation-batch-v1",
        relation_strategy="shared_context_batch",
        enable_entity_alignment=True,
        enable_retrieval=True,
        enable_schema_validation=True,
    ),
}


def get_method_profile(method_id: str) -> MethodProfile:
    try:
        return METHOD_PROFILES[method_id]
    except KeyError as exc:
        raise ValueError(f"未知实验方法 Profile：{method_id}") from exc
