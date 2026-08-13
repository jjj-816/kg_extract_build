import unittest
from types import SimpleNamespace
from unittest.mock import patch

from kg_extract_build.audit.production_composition import ProductionAuditComposition


class Graph:
    def query_clues(self, **kwargs):
        return [{"clue_id": "c1", "assertion_id": "a1", "relationship_type": "USES", "hops": 1, "source_document_id": "d1", "evidence_sentence": "sentence", "confirmed_case": True}]


class ProductionCompositionTests(unittest.TestCase):
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
