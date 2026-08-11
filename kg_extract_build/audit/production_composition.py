"""Single production composition seam between the UI and AuditOrchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .bounded_graph import GraphRetrievalResult, retrieve_bounded_clues
from .compliance_runtime import ComplianceRuntime
from .reasonableness import ReasonablenessRuntime


@dataclass(frozen=True)
class ProductionAuditComposition:
    compliance_runtime: ComplianceRuntime
    reasonableness_runtime: ReasonablenessRuntime
    graph_results: Mapping[str, GraphRetrievalResult]
    normative_search: Callable[..., Mapping[str, Any]]
    config_snapshot: Mapping[str, Any]

    @classmethod
    def build(
        cls,
        *,
        normative_search: Callable[..., Mapping[str, Any]],
        compliance_model: Callable[..., Mapping[str, Any]],
        reasonableness_model: Callable[..., Mapping[str, Any]] | None,
        graph,
        graph_queries: Mapping[str, Mapping[str, Any]],
        config_snapshot: Mapping[str, Any],
    ) -> "ProductionAuditComposition":
        graph_results: dict[str, GraphRetrievalResult] = {}
        for task_id, config in graph_queries.items():
            if graph is None:
                graph_results[task_id] = GraphRetrievalResult((), True, "图服务未配置，已降级为人工复核")
                continue
            graph_results[task_id] = retrieve_bounded_clues(
                graph,
                task_id=task_id,
                query=str(config.get("query", "")),
                relationship_whitelist=tuple(config.get("relationship_types", ())),
                max_hops=int(config.get("max_hops", 2)),
            )
        return cls(
            ComplianceRuntime(normative_search, compliance_model),
            ReasonablenessRuntime(reasonableness_model),
            graph_results,
            normative_search,
            dict(config_snapshot),
        )

    def as_audit_context(self) -> dict[str, Any]:
        return {
            "compliance_runtime": self.compliance_runtime,
            "reasonableness_runtime": self.reasonableness_runtime,
            "graph_results": dict(self.graph_results),
            "normative_search": self.normative_search,
            "production_config_snapshot": dict(self.config_snapshot),
        }
