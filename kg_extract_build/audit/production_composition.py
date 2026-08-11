"""Single production composition seam between the UI and AuditOrchestrator."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Mapping

from .bounded_graph import GraphRetrievalResult, retrieve_bounded_clues
from .compliance_runtime import ComplianceRuntime
from .reasonableness import ReasonablenessRuntime
from .normative_production import PublishedNormativeAdapter


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

    @classmethod
    def from_env(cls, *, model, scope, config_snapshot, graph_queries):
        """Build the production dependencies from the configured services."""
        from ..normative_encoder import EncoderProfile, NormativeEncoder, model_revision
        from ..normative_persistence import NormativeStore
        from ..normative_search import NormativeSearcher
        from ..normative_vector_store import NormativeMilvusStore
        from ..persistence import MySQLExperimentStore
        from .. import settings

        release_id = os.getenv("KG_AUDIT_NORMATIVE_RELEASE_ID", "").strip()
        if not release_id:
            raise ValueError("KG_AUDIT_NORMATIVE_RELEASE_ID must select a published release")
        profile = EncoderProfile(
            embedding_model_key="paraphrase-multilingual-MiniLM-L12-v2",
            embedding_model_revision=model_revision(settings.NORM_VECTOR_MODEL_PATH),
            embedding_dimension=384,
        )
        backend = MySQLExperimentStore.from_env()
        store = NormativeStore(backend)
        searcher = NormativeSearcher(
            store, NormativeMilvusStore.from_env(), NormativeEncoder(settings.NORM_VECTOR_MODEL_PATH, profile), profile,
        )
        adapter = PublishedNormativeAdapter(store, searcher)
        graph = None
        if os.getenv("KG_AUDIT_NEO4J_ENABLED", "1") == "1":
            from .neo4j_readonly import Neo4jReadOnlyGraph
            graph = Neo4jReadOnlyGraph.from_env()
        return cls.build(
            normative_search=lambda **kwargs: adapter.search(
                query=kwargs.get("query", ""), audit_year=scope.audit_year,
                release_id=release_id, scope=scope, top_k=kwargs.get("top_k", 5),
            ),
            compliance_model=model,
            reasonableness_model=model,
            graph=graph,
            graph_queries=graph_queries,
            config_snapshot={**dict(config_snapshot), "normative_release_id": release_id, "encoder_profile": profile.__dict__},
        )
