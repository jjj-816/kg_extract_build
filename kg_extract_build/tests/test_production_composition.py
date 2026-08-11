import unittest

from kg_extract_build.audit.production_composition import ProductionAuditComposition


class Graph:
    def query_clues(self, **kwargs):
        return [{"clue_id": "c1", "assertion_id": "a1", "relationship_type": "USES", "hops": 1, "source_document_id": "d1", "evidence_sentence": "sentence", "confirmed_case": True}]


class ProductionCompositionTests(unittest.TestCase):
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
