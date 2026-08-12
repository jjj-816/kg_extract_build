"""Single production composition seam between the UI and AuditOrchestrator."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Mapping

from .bounded_graph import GraphRetrievalResult, retrieve_bounded_clues
from .compliance_runtime import ComplianceRuntime
from .reasonableness import ReasonablenessRuntime
from .normative_production import PublishedNormativeAdapter
from .normative_scope import NormativeScopePreflight
from .retrieval_planner import TaskRetrievalPlanner


@dataclass(frozen=True)
class ProductionAuditComposition:
    compliance_runtime: ComplianceRuntime
    reasonableness_runtime: ReasonablenessRuntime
    graph_results: Mapping[str, GraphRetrievalResult]
    normative_search: Callable[..., Mapping[str, Any]]
    config_snapshot: Mapping[str, Any]
    scope_preflight: NormativeScopePreflight | None = None
    retrieval_planner: TaskRetrievalPlanner | None = None
    graph_adapter: Any | None = None
    graph_relationship_types: tuple[str, ...] = ()

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
        scope_preflight: NormativeScopePreflight | None = None,
        retrieval_planner: TaskRetrievalPlanner | None = None,
        graph_adapter: Any | None = None,
        graph_relationship_types: tuple[str, ...] = (),
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
            ComplianceRuntime(normative_search, compliance_model, retrieval_planner),
            ReasonablenessRuntime(reasonableness_model),
            graph_results,
            normative_search,
            dict(config_snapshot),
            scope_preflight,
            retrieval_planner,
            graph_adapter,
            graph_relationship_types,
        )

    def as_audit_context(self) -> dict[str, Any]:
        return {
            "compliance_runtime": self.compliance_runtime,
            "reasonableness_runtime": self.reasonableness_runtime,
            "graph_results": dict(self.graph_results),
            "normative_search": self.normative_search,
            "production_config_snapshot": dict(self.config_snapshot),
            "scope_preflight": self.scope_preflight,
            "retrieval_planner": self.retrieval_planner,
            "graph_adapter": self.graph_adapter,
            "graph_relationship_types": self.graph_relationship_types,
        }

    @classmethod
    def from_env(cls, *, model, scope, config_snapshot, graph_queries, release_id: str | None = None):
        """Build the production dependencies from the configured services."""
        from ..normative_encoder import EncoderProfile, NormativeEncoder, model_revision
        from ..normative_persistence import NormativeStore
        from ..normative_search import NormativeSearcher
        from ..normative_vector_store import NormativeMilvusStore
        from ..persistence import MySQLExperimentStore
        from .. import settings

        backend = MySQLExperimentStore.from_env()
        store = NormativeStore(backend)
        release_id = (release_id or os.getenv("KG_AUDIT_NORMATIVE_RELEASE_ID", "")).strip()
        # A release is optional for daily audit. If supplied, retain it only as
        # a replay/configuration reference; enabled corpus membership is used
        # for coverage and search.
        if release_id:
            release_rows = store._read(
                "SELECT release_id FROM kg_normative_index_release "
                "WHERE release_id=%s AND status='published'", (release_id,)
            )
            if not release_rows:
                release_id = ""
        profile = EncoderProfile(
            embedding_model_key="paraphrase-multilingual-MiniLM-L12-v2",
            embedding_model_revision=model_revision(settings.NORM_VECTOR_MODEL_PATH),
            embedding_dimension=384,
        )
        searcher = NormativeSearcher(
            store, NormativeMilvusStore.from_env(), NormativeEncoder(settings.NORM_VECTOR_MODEL_PATH, profile), profile,
        )
        adapter = PublishedNormativeAdapter(store, searcher)
        if not store.list_audit_enabled_indexes():
            raise ValueError("no enabled ready normative index is available")
        graph = None
        if os.getenv("KG_AUDIT_NEO4J_ENABLED", "1") == "1":
            from .neo4j_readonly import Neo4jReadOnlyGraph
            graph = Neo4jReadOnlyGraph.from_env()
        scope_preflight = adapter.preflight(scope, release_id)
        return cls.build(
            normative_search=lambda **kwargs: adapter.search(
                query=kwargs.get("query", ""), audit_year=scope.audit_year,
                release_id=release_id, scope=scope, top_k=kwargs.get("top_k", 5),
            ),
            compliance_model=model,
            reasonableness_model=model,
            graph=graph,
            graph_queries=graph_queries,
            config_snapshot={**dict(config_snapshot), "normative_release_id": release_id or None, "normative_corpus": "enabled_ready_indexes", "encoder_profile": profile.__dict__},
            scope_preflight=scope_preflight,
            retrieval_planner=TaskRetrievalPlanner(getattr(model, "retrieval_planner", None), prompt_version="retrieval-plan-v1"),
            graph_adapter=graph,
            graph_relationship_types=tuple(os.getenv("KG_AUDIT_GRAPH_RELATION_TYPES", "USES,REQUIRES,CONTROLS").split(",")),
        )
