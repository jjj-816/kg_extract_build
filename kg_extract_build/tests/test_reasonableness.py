import unittest

from kg_extract_build.audit.bounded_graph import GraphClue, GraphRetrievalResult
from kg_extract_build.audit.reasonableness import ReasonablenessRuntime
from kg_extract_build.audit.models import AuditTaskDefinition


TASK = AuditTaskDefinition("R-1", 1, "s", "合理性", "content_semantic", "semantic_reasonableness", None, "document", (), (), (), (), (), "stage", "all")


class ReasonablenessTests(unittest.TestCase):
    def test_graph_unavailable_degrades_to_manual_review(self):
        result = ReasonablenessRuntime().run(TASK, [{"block_id": "d1"}], GraphRetrievalResult((), True, "图服务不可用"), "run")
        self.assertEqual(result.result_status, "manual_review")
        self.assertIn("图服务不可用", result.diagnostics[0])

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


if __name__ == "__main__":
    unittest.main()
