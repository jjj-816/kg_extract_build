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
    enable_llm_alignment: bool
    enable_retrieval: bool
    enable_shared_grouping: bool
    enable_context_deduplication: bool
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
        enable_llm_alignment=False,
        enable_retrieval=False,
        enable_shared_grouping=False,
        enable_context_deduplication=False,
        enable_schema_validation=False,
    ),
    "R3": MethodProfile(
        method_id="R3",
        label="R3 · Single-Entity",
        description="实体对齐后逐实体检索与抽取；不使用共享批次和后置模式校验。",
        prompt_version="single-entity-v1",
        relation_strategy="single_entity",
        enable_entity_alignment=True,
        enable_llm_alignment=True,
        enable_retrieval=True,
        enable_shared_grouping=False,
        enable_context_deduplication=True,
        enable_schema_validation=False,
    ),
    "R4": MethodProfile(
        method_id="R4",
        label="R4 · Fixed-Batch",
        description="实体对齐和检索后按固定实体数顺序分批；不按证据重叠分组，也不进行后置模式校验。",
        prompt_version="relation-batch-v1",
        relation_strategy="fixed_batch",
        enable_entity_alignment=True,
        enable_llm_alignment=True,
        enable_retrieval=True,
        enable_shared_grouping=False,
        enable_context_deduplication=True,
        enable_schema_validation=False,
    ),
    "R5": MethodProfile(
        method_id="R5",
        label="R5 · Shared-Context-Batch",
        description="实体对齐和检索后，按共享证据构建上下文批次；不进行后置模式校验。",
        prompt_version="relation-batch-v1",
        relation_strategy="shared_context_batch",
        enable_entity_alignment=True,
        enable_llm_alignment=True,
        enable_retrieval=True,
        enable_shared_grouping=True,
        enable_context_deduplication=True,
        enable_schema_validation=False,
    ),
    "R6": MethodProfile(
        method_id="R6",
        label="R6 · Full Method",
        description="完整方法：实体对齐、检索、共享上下文批量抽取和后置模式校验。",
        prompt_version="relation-batch-v1",
        relation_strategy="shared_context_batch",
        enable_entity_alignment=True,
        enable_llm_alignment=True,
        enable_retrieval=True,
        enable_shared_grouping=True,
        enable_context_deduplication=True,
        enable_schema_validation=True,
    ),
    "D0": MethodProfile("D0", "D0 · Full Method（复用 R6）", "消融基准，与 R6 完全相同。", "relation-batch-v1", "shared_context_batch", True, True, True, True, True, True),
    "D1": MethodProfile("D1", "D1 · 无实体对齐", "仅移除实体对齐，直接将原始实体作为后续抽取头实体。", "relation-batch-v1", "shared_context_batch", False, False, True, True, True, True),
    "D2": MethodProfile("D2", "D2 · 无 LLM 对齐", "保留规则/向量候选分组，仅移除 LLM 对齐判定。", "relation-batch-v1", "shared_context_batch", True, False, True, True, True, True),
    "D3": MethodProfile("D3", "D3 · 无检索", "保留其他模块，但每个实体使用所在位置的局部上下文，不做实体条件检索。", "relation-batch-v1", "shared_context_batch", True, True, False, True, True, True),
    "D4": MethodProfile("D4", "D4 · 无共享分组", "保留其他模块，改用固定顺序批次而不是按共享证据分组。", "relation-batch-v1", "fixed_batch", True, True, True, False, True, True),
    "D5": MethodProfile("D5", "D5 · 无上下文去重", "保留其他模块，但共享批次中保留同一句证据的重复出现。", "relation-batch-v1", "shared_context_batch", True, True, True, True, False, True),
    "D6": MethodProfile("D6", "D6 · 无 Schema 校验（复用 R5）", "仅移除后置 Schema 校验，与 R5 完全相同。", "relation-batch-v1", "shared_context_batch", True, True, True, True, True, False),
}


def get_method_profile(method_id: str) -> MethodProfile:
    try:
        return METHOD_PROFILES[method_id]
    except KeyError as exc:
        raise ValueError(f"未知实验方法 Profile：{method_id}") from exc
