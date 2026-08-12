import unittest
from types import SimpleNamespace

from kg_extract_build.audit.retrieval_planner import TaskRetrievalPlanner


class RetrievalPlannerTests(unittest.TestCase):
    def test_planner_returns_only_anchored_queries(self):
        task = SimpleNamespace(task_id="BASIS-002")
        planner = TaskRetrievalPlanner(lambda task, evidence, mode: {"document_block_ids": ["b1", "missing"], "normative_queries": ["安全", "安全"], "graph_queries": ["历史案例"]})
        plan = planner.plan(task, ({"block_id": "b1", "raw_text": "方案证据"},))
        self.assertEqual(plan.document_block_ids, ("b1",))
        self.assertEqual(plan.normative_queries, ("安全",))
        self.assertEqual(plan.graph_queries, ("历史案例",))
        self.assertNotIn("result_status", plan.to_record())
        self.assertNotIn("evidence_id", plan.to_record())

    def test_no_evidence_does_not_call_model_or_create_plan(self):
        called = []
        planner = TaskRetrievalPlanner(lambda *args: called.append(True))
        plan = planner.plan(SimpleNamespace(task_id="T1"), ())
        self.assertEqual(called, [])
        self.assertEqual(plan.normative_queries, ())
        self.assertTrue(plan.diagnostics)

    def test_relationships_are_limited_to_schema(self):
        planner = TaskRetrievalPlanner(
            lambda task, evidence, mode: {
                "document_block_ids": ["b1"],
                "graph_queries": ["设备"],
                "relationship_types": ["USES_EQUIPMENT", "NOT_IN_SCHEMA"],
            },
            allowed_relationships=("USES_EQUIPMENT", "HAS_PARAMETER"),
        )
        plan = planner.plan(SimpleNamespace(task_id="T2"), ({"block_id": "b1", "raw_text": "设备"},))
        self.assertEqual(plan.relationship_types, ("USES_EQUIPMENT",))
        self.assertIn("过滤", " ".join(plan.diagnostics))


if __name__ == "__main__":
    unittest.main()
