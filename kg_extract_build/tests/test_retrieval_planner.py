import unittest
from types import SimpleNamespace

from kg_extract_build.audit.retrieval_planner import TaskRetrievalPlanner


class RetrievalPlannerTests(unittest.TestCase):
    def test_plan_reads_strict_top_level_query_lists(self):
        planner = TaskRetrievalPlanner(
            lambda *_args, **_kwargs: {
                "document_block_ids": ["B1"],
                "normative_queries": ["高压管汇 试压 安全要求"],
                "graph_queries": ["高压管汇", "试压"],
                "relationship_types": ["USES_EQUIPMENT", "HAS_PARAMETER"],
            },
            allowed_relationships={"USES_EQUIPMENT", "HAS_PARAMETER"},
        )

        plan = planner.plan(
            SimpleNamespace(task_id="T1"),
            [{"block_id": "B1", "raw_text": "高压管汇试压"}],
        )

        self.assertEqual(plan.normative_queries, ("高压管汇 试压 安全要求",))
        self.assertEqual(plan.graph_queries, ("高压管汇", "试压"))

    def test_plan_rejects_retrieval_plan_shape_with_action_keywords(self):
        planner = TaskRetrievalPlanner(
            lambda *_args, **_kwargs: {
                "retrieval_plan": [{"keywords": ["设备适配性"]}],
            },
        )

        plan = planner.plan(SimpleNamespace(task_id="T1"), [{"block_id": "B1"}])

        self.assertIn("检索规划输出不符合受控 JSON 契约", plan.diagnostics)
        self.assertEqual(plan.normative_queries, ())

    def test_plan_records_empty_top_level_list_diagnostics(self):
        planner = TaskRetrievalPlanner(
            lambda *_args, **_kwargs: {
                "document_block_ids": [],
                "normative_queries": [],
                "graph_queries": [],
                "relationship_types": [],
            },
        )

        plan = planner.plan(SimpleNamespace(task_id="T1"), [{"block_id": "B1"}])

        self.assertIn("document_block_ids 为空列表", plan.diagnostics)
        self.assertIn("normative_queries 为空列表", plan.diagnostics)
        self.assertIn("graph_queries 为空列表", plan.diagnostics)
        self.assertIn("relationship_types 为空列表", plan.diagnostics)

    def test_planner_returns_only_anchored_queries(self):
        task = SimpleNamespace(task_id="BASIS-002")
        planner = TaskRetrievalPlanner(lambda task, evidence, mode: {"document_block_ids": ["b1", "missing"], "normative_queries": ["安全", "安全"], "graph_queries": ["历史案例"], "relationship_types": []})
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
                "normative_queries": [],
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
