"""Evidence-anchored retrieval planning, separate from semantic conclusions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


class RetrievalPlanError(ValueError):
    pass


@dataclass(frozen=True)
class GraphQueryEntity:
    name: str
    entity_type: str
    evidence_block_ids: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalPlan:
    task_id: str
    prompt_version: str
    document_block_ids: tuple[str, ...]
    normative_queries: tuple[str, ...]
    graph_queries: tuple[str, ...]
    relationship_types: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    graph_entities: tuple[GraphQueryEntity, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "prompt_version": self.prompt_version,
            "document_block_ids": list(self.document_block_ids),
            "normative_queries": list(self.normative_queries),
            "graph_queries": list(self.graph_queries),
            "relationship_types": list(self.relationship_types),
            "diagnostics": list(self.diagnostics),
            "graph_entities": [
                {"name": item.name, "entity_type": item.entity_type, "evidence_block_ids": list(item.evidence_block_ids)}
                for item in self.graph_entities
            ],
        }


class TaskRetrievalPlanner:
    def __init__(self, model: Callable[..., Mapping[str, Any]] | None = None, prompt_version: str = "retrieval-plan-v1", allowed_relationships=(), allowed_entity_types=(), graph_entity_extractor=None):
        self.model = model
        self.prompt_version = prompt_version
        self.allowed_relationships = frozenset(str(item) for item in allowed_relationships if str(item).strip())
        self.allowed_entity_types = frozenset(str(item) for item in allowed_entity_types if str(item).strip())
        self.graph_entity_extractor = graph_entity_extractor

    def plan(self, task, evidence: tuple[dict, ...] | list[dict]) -> RetrievalPlan:
        evidence = tuple(dict(item) for item in evidence)
        block_ids = tuple(str(item.get("block_id")) for item in evidence if item.get("block_id"))
        if not block_ids:
            return RetrievalPlan(task.task_id, self.prompt_version, (), (), (), (), ("无方案证据锚点，未生成检索计划",))
        raw: Mapping[str, Any] = {}
        diagnostics: list[str] = []
        graph_entities = self._graph_entities(task, evidence, block_ids, diagnostics)
        if self.model is not None:
            try:
                try:
                    raw = self.model(task, evidence, mode="retrieval_planning", instruction=getattr(task, "retrieval_instruction", "")) or {}
                except TypeError:
                    raw = self.model(task, evidence, mode="retrieval_planning") or {}
            except Exception as exc:
                diagnostics.append(f"检索规划模型失败：{exc}")
                raw = {}
        controlled = self._controlled_lists(raw, diagnostics)
        raw_relationships: tuple[str, ...] = ()
        if controlled is None:
            recovered = self._compatible_queries(raw)
            if recovered:
                normative = graph = recovered
                relationships = tuple(sorted(self.allowed_relationships))
                diagnostics.append("planning_mode=compatibility_recovered")
            else:
                normative = graph = ()
                relationships = tuple(sorted(self.allowed_relationships))
                diagnostics.append("planning_mode=query_generation_failed")
            anchors = block_ids
        else:
            normative = self._queries(controlled["normative_queries"])
            graph = self._queries(controlled["graph_queries"])
            raw_relationships = self._queries(controlled["relationship_types"])
            relationships = tuple(
                item for item in raw_relationships
                if not self.allowed_relationships or item in self.allowed_relationships
            )
            if not relationships and self.allowed_relationships:
                relationships = tuple(self.allowed_relationships)
            anchors = tuple(item for item in controlled["document_block_ids"] if item in block_ids)
            unknown_anchors = tuple(item for item in controlled["document_block_ids"] if item not in block_ids)
            if unknown_anchors:
                diagnostics.append("document_block_ids 包含不存在的证据锚点")
            if not anchors:
                anchors = block_ids
                diagnostics.append("模型未返回有效证据锚点，回退为全部方案证据")
            if not graph:
                diagnostics.append("planning_mode=query_generation_failed")
        if not normative and not graph:
            diagnostics.append("未生成规范或图查询词")
        interaction = getattr(self.model, "last_interaction", None)
        if interaction:
            diagnostics.append("retrieval_planner_io_captured")
        if raw_relationships and len(raw_relationships) != len(relationships):
            diagnostics.append("模型返回的关系不在完整 Schema 中，已过滤")
        if graph_entities:
            graph = tuple(item.name for item in graph_entities)
            diagnostics.append("graph_query_mode=entity_extraction")
        return RetrievalPlan(task.task_id, self.prompt_version, anchors, normative, graph, relationships, tuple(diagnostics), graph_entities)

    def _graph_entities(self, task, evidence, block_ids: tuple[str, ...], diagnostics: list[str]) -> tuple[GraphQueryEntity, ...]:
        if self.graph_entity_extractor is None:
            return ()
        try:
            raw = self.graph_entity_extractor(task, evidence, tuple(sorted(self.allowed_entity_types))) or {}
        except Exception as exc:
            diagnostics.append(f"图检索实体抽取模型失败：{exc}")
            return ()
        entities = raw.get("entities", ()) if isinstance(raw, Mapping) else ()
        if not isinstance(entities, list):
            diagnostics.append("图检索实体抽取输出不符合受控 JSON 契约")
            return ()
        result: list[GraphQueryEntity] = []
        seen: set[tuple[str, str]] = set()
        raw_text_by_id = {str(item.get("block_id")): str(item.get("raw_text") or "") for item in evidence}
        for item in entities:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or "").strip()
            entity_type = str(item.get("type") or "").strip()
            evidence_ids = tuple(str(value) for value in item.get("evidence_block_ids", ()) if str(value) in block_ids)
            if not 2 <= len(name) <= 40 or entity_type not in self.allowed_entity_types or not evidence_ids:
                continue
            if not any(name in raw_text_by_id[block_id] for block_id in evidence_ids):
                continue
            key = (name, entity_type)
            if key in seen:
                continue
            seen.add(key)
            result.append(GraphQueryEntity(name, entity_type, evidence_ids))
            if len(result) == 8:
                break
        return tuple(result)

    @staticmethod
    def _controlled_lists(raw: Mapping[str, Any], diagnostics: list[str]) -> dict[str, list[str]] | None:
        fields = ("document_block_ids", "normative_queries", "graph_queries", "relationship_types")
        if not isinstance(raw, Mapping) or set(raw) != set(fields):
            diagnostics.append("检索规划输出不符合受控 JSON 契约")
            return None
        result: dict[str, list[str]] = {}
        for field in fields:
            values = raw[field]
            if not isinstance(values, list):
                diagnostics.append(f"{field} 必须是列表")
                return None
            if len(values) > 5 or any(not isinstance(value, str) for value in values):
                diagnostics.append("检索规划输出不符合受控 JSON 契约")
                return None
            if not values:
                diagnostics.append(f"{field} 为空列表")
            result[field] = values
        return result

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

    @classmethod
    def _compatible_queries(cls, raw: Mapping[str, Any]) -> tuple[str, ...]:
        if not isinstance(raw, Mapping):
            return ()
        values: list[Any] = []
        for field in ("retrieval_queries", "search_queries", "case_hints", "retrieval_keywords"):
            value = raw.get(field, ())
            if isinstance(value, list):
                values.extend(value)
        plans = raw.get("retrieval_plan", ())
        if isinstance(plans, list):
            for item in plans:
                if isinstance(item, Mapping) and isinstance(item.get("keywords"), list):
                    values.extend(item["keywords"])
        elif isinstance(plans, Mapping):
            values.extend(cls._query_values(plans.get("queries", ())))
            values.extend(cls._query_values(plans.get("retrieval_actions", ())))
        plan = raw.get("plan", {})
        if isinstance(plan, Mapping):
            values.extend(cls._query_values(plan.get("queries", ())))
        return cls._queries(values)

    @staticmethod
    def _query_values(value) -> list[Any]:
        if not isinstance(value, list):
            return []
        extracted: list[Any] = []
        for item in value:
            if isinstance(item, str):
                extracted.append(item)
            elif isinstance(item, Mapping):
                query = item.get("query")
                if isinstance(query, str):
                    extracted.append(query)
                keywords = item.get("keywords")
                if isinstance(keywords, list):
                    extracted.extend(keywords)
        return extracted
