import unittest
from types import SimpleNamespace
from unittest.mock import patch

from kg_extract_build.audit.executor import AuditOrchestrator
from kg_extract_build.audit.models import AuditDocumentBlock, AuditTaskDefinition, ParsedAuditDocument, StoredAuditDocument, TaskEvidenceGroup, TaskLocationResult
from kg_extract_build.audit.persistence import MySQLAuditStore
from kg_extract_build.audit.production_composition import ProductionAuditComposition
from kg_extract_build.audit.retrieval_planner import RetrievalPlan


class Graph:
    def query_clues(self, **kwargs):
        return [{"clue_id": "c1", "assertion_id": "a1", "relationship_type": "USES", "hops": 1, "source_document_id": "d1", "evidence_sentence": "sentence", "confirmed_case": True}]


class ProductionCompositionTests(unittest.TestCase):
    def test_production_trace_persistence_precedes_graph_adapter_call(self):
        events = []

        class TraceStore(MySQLAuditStore):
            def save_execution_trace_entry(self, run_id, task_id, entry, *, provider_id, model_name):
                events.append(("persist", run_id, task_id, entry["stage"], provider_id, model_name))

        class Planner:
            model = None

            def plan(self, task, evidence):
                return RetrievalPlan(task.task_id, "retrieval-v1", ("heading", "table"), (), ("pump",), ("USES",), ())

        class GraphAdapter:
            def query_clues(self, **kwargs):
                events.append(("graph", kwargs["query"]))
                return [{"clue_id": "c1", "assertion_id": "a1", "relationship_type": "USES", "hops": 1, "source_document_id": "d1", "evidence_sentence": "sentence", "confirmed_case": True}]

        task = AuditTaskDefinition("R-1", 1, "appendix", "reasonableness", "content_semantic", "semantic_reasonableness", None, "document", (), (), (), (), (), "stage", "all")
        blocks = (
            AuditDocumentBlock("heading", "doc", 1, "heading", ("appendix",), "word/body[1]/paragraph", "appendix", "appendix"),
            AuditDocumentBlock("table", "doc", 2, "table", ("appendix",), "word/body[2]/table[1]", "", "", table_json={"rows": [["equipment"], ["pump"]]}),
        )
        preview = SimpleNamespace(
            parsed_document=ParsedAuditDocument(StoredAuditDocument("doc", "plan.docx", "docx", "a" * 64, None, ""), blocks, 1, 1, 0, False),
            task_library=SimpleNamespace(tasks=(task,), task_library_id="test", version="1", sha256="a" * 64),
            locations={task.task_id: TaskLocationResult(task.task_id, "located", evidence_groups=(TaskEvidenceGroup("g", "heading", (), ("appendix",), (), 1, "test"),))},
        )
        graph = GraphAdapter()
        composition = ProductionAuditComposition.build(
            normative_search=lambda **kwargs: {"evidence": [], "coverage": []},
            compliance_model=lambda *args: {"result_status": "no_issue", "issues": []},
            reasonableness_model=None,
            graph=None,
            graph_queries={},
            config_snapshot={"provider": "provider-1", "model": "model-1"},
            retrieval_planner=Planner(),
            graph_adapter=graph,
            graph_relationship_types=("USES",),
        )
        store = TraceStore()
        context = composition.as_audit_context(
            execution_trace_recorder=store.execution_trace_recorder("run-1", provider_id="provider-1", model_name="model-1"),
        )

        AuditOrchestrator().execute_preview(preview, context, run_id="run-1")

        self.assertEqual(events[:2], [("persist", "run-1", "R-1", "retrieval_planning", "provider-1", "model-1"), ("graph", "pump")])

    def test_from_env_passes_schema_relationship_names_to_retrieval_planner(self):
        captured = {}

        class Store:
            def __init__(self, _backend):
                pass

            def list_audit_enabled_indexes(self):
                return [object()]

            def _read(self, *_args):
                return []

        class Adapter:
            def __init__(self, *_args):
                pass

            def preflight(self, *_args):
                return None

        def capture_build(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace()

        backend = SimpleNamespace(ensure_normative_audit_schema=lambda: None)
        schema = SimpleNamespace(relation_types=({"name": "USES_EQUIPMENT"}, {"name": "HAS_PARAMETER"}))
        model = SimpleNamespace(retrieval_planner=lambda *_args, **_kwargs: {})
        scope = SimpleNamespace(audit_year=2026)
        with (
            patch("kg_extract_build.persistence.MySQLExperimentStore.from_env", return_value=backend),
            patch("kg_extract_build.normative_persistence.NormativeStore", Store),
            patch("kg_extract_build.normative_vector_store.NormativeMilvusStore.from_env", return_value=object()),
            patch("kg_extract_build.normative_encoder.NormativeEncoder", return_value=object()),
            patch("kg_extract_build.normative_encoder.model_revision", return_value="revision"),
            patch("kg_extract_build.audit.production_composition.PublishedNormativeAdapter", Adapter),
            patch("kg_extract_build.schema.KGSchema", return_value=schema),
            patch("kg_extract_build.audit.production_composition.ProductionAuditComposition.build", side_effect=capture_build),
            patch.dict("os.environ", {"KG_AUDIT_NEO4J_ENABLED": "0"}, clear=False),
        ):
            ProductionAuditComposition.from_env(
                model=model, scope=scope, config_snapshot={}, graph_queries={},
            )

        self.assertEqual(
            captured["retrieval_planner"].allowed_relationships,
            frozenset({"USES_EQUIPMENT", "HAS_PARAMETER"}),
        )

    def test_build_routes_graph_and_runtime_seams(self):
        composition = ProductionAuditComposition.build(
            normative_search=lambda **kwargs: {"evidence": [], "coverage": []},
            compliance_model=lambda *args: {"result_status": "no_issue", "issues": []},
            reasonableness_model=None,
            graph=Graph(),
            graph_queries={"APPD-004": {"query": "pump", "relationship_types": ("USES",), "max_hops": 2}},
            config_snapshot={"release_id": "rel-1", "prompt_version": "v1"},
        )
        context = composition.as_audit_context()
        self.assertIn("compliance_runtime", context)
        self.assertEqual(context["graph_results"]["APPD-004"].clues[0].assertion_id, "a1")
        self.assertEqual(context["production_config_snapshot"]["release_id"], "rel-1")


if __name__ == "__main__":
    unittest.main()
