"""Evidence-anchored retrieval planning, separate from semantic conclusions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


class RetrievalPlanError(ValueError):
    pass


@dataclass(frozen=True)
class RetrievalPlan:
    task_id: str
    prompt_version: str
    document_block_ids: tuple[str, ...]
    normative_queries: tuple[str, ...]
    graph_queries: tuple[str, ...]
    relationship_types: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "prompt_version": self.prompt_version,
            "document_block_ids": list(self.document_block_ids),
            "normative_queries": list(self.normative_queries),
            "graph_queries": list(self.graph_queries),
            "relationship_types": list(self.relationship_types),
            "diagnostics": list(self.diagnostics),
        }


class TaskRetrievalPlanner:
    def __init__(self, model: Callable[..., Mapping[str, Any]] | None = None, prompt_version: str = "retrieval-plan-v1", allowed_relationships=()):
        self.model = model
        self.prompt_version = prompt_version
        self.allowed_relationships = frozenset(str(item) for item in allowed_relationships if str(item).strip())

    def plan(self, task, evidence: tuple[dict, ...] | list[dict]) -> RetrievalPlan:
        evidence = tuple(dict(item) for item in evidence)
        block_ids = tuple(str(item.get("block_id")) for item in evidence if item.get("block_id"))
        if not block_ids:
            return RetrievalPlan(task.task_id, self.prompt_version, (), (), (), (), ("无方案证据锚点，未生成检索计划",))
        raw: Mapping[str, Any] = {}
        diagnostics: list[str] = []
        if self.model is not None:
            try:
                try:
                    raw = self.model(task, evidence, mode="retrieval_planning", instruction=getattr(task, "retrieval_instruction", "")) or {}
                except TypeError:
                    raw = self.model(task, evidence, mode="retrieval_planning") or {}
            except Exception as exc:
                diagnostics.append(f"检索规划模型失败：{exc}")
                raw = {}
        try:
            normative = self._queries(raw.get("normative_queries", ()))
            graph = self._queries(raw.get("graph_queries", ()))
            relationships = tuple(
                item for item in self._queries(raw.get("relationship_types", ()))
                if not self.allowed_relationships or item in self.allowed_relationships
            )
        except RetrievalPlanError as exc:
            diagnostics.append(str(exc))
            normative, graph, relationships = (), (), ()
        anchors = tuple(str(item) for item in raw.get("document_block_ids", block_ids) if str(item) in block_ids)
        if not anchors:
            anchors = block_ids
            diagnostics.append("模型未返回有效证据锚点，回退为全部方案证据")
        if not normative and not graph:
            diagnostics.append("未生成规范或图查询词")
        interaction = getattr(self.model, "last_interaction", None)
        if interaction:
            diagnostics.append("retrieval_planner_io_captured")
        raw_relationships = tuple(self._queries(raw.get("relationship_types", ()))) if raw.get("relationship_types") else ()
        if raw_relationships and len(raw_relationships) != len(relationships):
            diagnostics.append("模型返回的关系不在完整 Schema 中，已过滤")
        return RetrievalPlan(task.task_id, self.prompt_version, anchors, normative, graph, relationships, tuple(diagnostics))

    @staticmethod
    def _queries(values) -> tuple[str, ...]:
        if not isinstance(values, (list, tuple)):
            raise RetrievalPlanError("检索查询词必须是列表")
        result = []
        for value in values:
            text = str(value).strip()
            if text and text not in result:
                result.append(text)
        return tuple(result[:5])
