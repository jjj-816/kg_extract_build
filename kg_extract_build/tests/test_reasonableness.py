import unittest

from kg_extract_build.audit.bounded_graph import GraphClue, GraphRetrievalResult
from kg_extract_build.audit.reasonableness import ReasonablenessRuntime, build_retrieval_planning_trace
from kg_extract_build.audit.models import AuditTaskDefinition


TASK = AuditTaskDefinition("R-1", 1, "s", "合理性", "content_semantic", "semantic_reasonableness", None, "document", (), (), (), (), (), "stage", "all")


class ReasonablenessTests(unittest.TestCase):
    def test_planning_trace_contains_extracted_graph_entities_and_entity_llm_io(self):
        from kg_extract_build.audit.retrieval_planner import GraphQueryEntity, RetrievalPlan
        plan = RetrievalPlan(
            "T1", "v1", ("B1",), (), ("地下管线",), ("HAS_PARAMETER",), (),
            (GraphQueryEntity("地下管线", "施工对象", ("B1",)),),
        )
        trace = build_retrieval_planning_trace(
            plan, [{"block_id": "B1", "raw_text": "确认地下管线"}],
            graph_entity_interaction={"raw_response": '{"entities":[]}', "correction_raw_response": None},
        )
        self.assertEqual(trace["output"]["graph_entities"][0]["name"], "地下管线")
        self.assertEqual(trace["output"]["graph_entity_llm_raw_response"], '{"entities":[]}')

    def test_graph_unavailable_degrades_to_manual_review(self):
        result = ReasonablenessRuntime().run(TASK, [{"block_id": "d1"}], GraphRetrievalResult((), True, "图服务不可用"), "run")
        self.assertEqual(result.execution_status, "failed")
        self.assertIsNone(result.result_status)
        self.assertIn("图服务不可用", result.diagnostics[0])

    def test_graph_mapping_failure_skips_model(self):
        called = []

        def model(*args, **kwargs):
            called.append(True)
            return {}

        result = ReasonablenessRuntime(model).run(
            TASK, (), GraphRetrievalResult((), True, "图字段映射失败"), "run"
        )
        self.assertEqual(result.execution_status, "failed")
        self.assertIn("图字段映射失败", result.diagnostics[0])
        self.assertEqual(called, [])

    def test_graph_clues_are_separate_and_second_search_runs_once(self):
        clue = GraphClue("c1", "R-1", "USES", 1, "a1", "doc-old", "历史句子", "提示")
        calls = []
        def search(**kwargs):
            calls.append(kwargs)
            return {"evidence": []}
        def model(*_args, **_kwargs):
            return {"needs_normative_candidates": True, "normative_query": "规范候选", "issues": [{"summary": "设备风险"}]}
        result = ReasonablenessRuntime(model).run(TASK, [{"block_id": "d1", "evidence_type": "document"}], GraphRetrievalResult((clue,)), "run", search)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.result_status, "manual_review")
        self.assertEqual([item["evidence_type"] for item in result.evidence if "evidence_type" in item], ["document", "graph_clue"])
        self.assertNotIn("规范不符合", result.manual_reviews[0].summary)


    def test_model_description_becomes_observed_conclusion(self):
        clue = GraphClue("c1", "R-1", "PRECEDES", 1, "a1", "doc-old", "baseline sequence", "sequence")

        def model(*_args, **_kwargs):
            return {
                "issues": [{
                    "description": "Cable trenching is placed before the safety briefing.",
                    "suggestion": "Brief workers before construction.",
                }]
            }

        result = ReasonablenessRuntime(model).run(
            TASK, [{"block_id": "d1", "raw_text": "sequence"}], GraphRetrievalResult((clue,)), "run"
        )

        self.assertEqual(result.manual_reviews[0].summary, "Cable trenching is placed before the safety briefing.")
        self.assertEqual(result.manual_reviews[0].suggestion, "Brief workers before construction.")

    def test_no_graph_clue_still_calls_model_for_manual_review_advisory(self):
        calls = []
        def model(*_args, **_kwargs):
            calls.append(True)
            return {"issues": [{"summary": "需核对现场隔离措施"}]}

        result = ReasonablenessRuntime(model).run(
            TASK, [{"block_id": "d1", "raw_text": "未确认危险区域隔离"}],
            GraphRetrievalResult((), False, "图查询已发起但无有效线索"), "run",
        )

        self.assertEqual(calls, [True])
        self.assertEqual(result.result_status, "manual_review")
        self.assertIn("需核对现场隔离措施", result.manual_reviews[0].summary)


if __name__ == "__main__":
    unittest.main()
