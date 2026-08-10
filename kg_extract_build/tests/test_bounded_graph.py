import unittest

from kg_extract_build.audit.bounded_graph import retrieve_bounded_clues


class FakeGraph:
    def __init__(self, rows=None, error=None):
        self.rows, self.error = rows or [], error
        self.calls = []

    def query_clues(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.rows


class BoundedGraphTests(unittest.TestCase):
    def test_filters_relationships_hops_and_requires_traceability(self):
        graph = FakeGraph([{"clue_id": "c1", "relationship_type": "USES", "hops": 2, "assertion_id": "a1", "source_document_id": "doc1", "evidence_sentence": "句子", "confirmed_case": True}, {"clue_id": "c2", "relationship_type": "OTHER", "hops": 1, "assertion_id": "a2", "source_document_id": "doc2", "evidence_sentence": "句子", "confirmed_case": True}, {"clue_id": "c3", "relationship_type": "USES", "hops": 3, "assertion_id": "a3", "source_document_id": "doc3", "evidence_sentence": "句子", "confirmed_case": True}])
        result = retrieve_bounded_clues(graph, task_id="T", query="设备", relationship_whitelist=["USES"])
        self.assertEqual([clue.clue_id for clue in result.clues], ["c1"])
        self.assertEqual(graph.calls[0]["max_hops"], 2)

    def test_graph_failure_degrades_without_business_conclusion(self):
        result = retrieve_bounded_clues(FakeGraph(error=ConnectionError("offline")), task_id="T", query="x", relationship_whitelist=["USES"])
        self.assertTrue(result.degraded)
        self.assertIn("信息不足", result.diagnostic)
        self.assertEqual(result.clues, ())


if __name__ == "__main__":
    unittest.main()
