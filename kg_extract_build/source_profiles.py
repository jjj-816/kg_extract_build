"""Source-aware extraction prompt profiles.

The pipeline stays shared for construction cases and normative documents; only
the extraction instructions and their versioned identity vary by source.
"""

from __future__ import annotations

from dataclasses import dataclass


SOURCE_TYPES = frozenset({"case", "spec", "auto"})
UI_SOURCE_TYPES = ("case", "spec")


@dataclass(frozen=True)
class SourcePromptProfile:
    source_type: str
    label: str
    prompt_version: str
    entity_guidance: str
    triplet_guidance: str


SOURCE_PROMPT_PROFILES = {
    "case": SourcePromptProfile(
        source_type="case",
        label="施工案例",
        prompt_version="case-v1",
        entity_guidance=(
            "重点识别作业活动、设备设施、人员角色、风险危害、控制措施、"
            "工艺参数和施工记录；只抽取原文出现的实体。"
        ),
        triplet_guidance=(
            "这是施工案例。关系必须来自原文对作业、风险、措施、角色或参数的"
            "明确描述，禁止把工程常识补写为事实。"
        ),
    ),
    "spec": SourcePromptProfile(
        source_type="spec",
        label="规范文件",
        prompt_version="spec-v1",
        entity_guidance=(
            "重点识别规制对象、强制措施、禁止行为、责任角色、审批要求、"
            "参数阈值、风险条件和记录要求；不得用工程常识补全规范条款。"
        ),
        triplet_guidance=(
            "这是规范文件。只抽取原文明确陈述的关系；不得将推测或解释写成"
            "规范要求。三元组仅是规范定位线索，完整条款原文才是最终证据。"
        ),
    ),
}


def infer_source_type(file_name: str) -> str:
    """Legacy filename heuristic, intentionally used only for ``auto``."""
    name = str(file_name or "")
    return "spec" if "规范" in name or "标准" in name else "case"


def resolve_source_type(requested: str, file_name: str = "") -> str:
    if requested not in SOURCE_TYPES:
        raise ValueError("文档来源类型必须是 case、spec 或 auto")
    return infer_source_type(file_name) if requested == "auto" else requested


def get_source_prompt_profile(source_type: str) -> SourcePromptProfile:
    try:
        return SOURCE_PROMPT_PROFILES[source_type]
    except KeyError as exc:
        raise ValueError("来源提示词仅支持 case 或 spec") from exc
