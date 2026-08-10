import unittest

from kg_extract_build.audit.ui_state import execution_summary, pending_review_task_ids, publish_gate, split_evidence, version_summary


class UIStateTests(unittest.TestCase):
    def setUp(self):
        self.report = {"tasks": [
            {"task_id": "C-1", "execution_status": "completed", "result_status": "issue_found", "manual_reviews": []},
            {"task_id": "R-1", "execution_status": "failed", "result_status": None, "manual_reviews": [{"summary": "复核"}]},
            {"task_id": "D-1", "execution_status": "pending", "result_status": None, "manual_reviews": []},
        ]}

    def test_execution_summary_keeps_failure_and_unexecuted_distinct(self):
        self.assertEqual(execution_summary(self.report), {"已完成": 1, "系统失败": 1, "未执行": 1, "人工复核/降级": 0})

    def test_evidence_and_publish_gate_are_type_safe(self):
        groups = split_evidence([{"block_id": "d"}, {"evidence_type": "normative_clause", "clause_id": "c"}, {"evidence_type": "graph_clue", "clue_id": "g"}])
        self.assertEqual([len(groups[key]) for key in ("document", "normative_clause", "graph_clue")], [1, 1, 1])
        self.assertEqual(pending_review_task_ids(self.report), ["R-1"])
        self.assertFalse(publish_gate(self.report)["can_publish"])
        self.report["tasks"][1]["human_review_status"] = "resolved"
        self.assertTrue(publish_gate(self.report)["can_publish"])

    def test_version_summary_is_display_ready(self):
        rows = version_summary([{"report_id": "r1", "status": "published", "version": 1, "generated_by": "审查员", "created_at": "now"}])
        self.assertEqual(rows[0]["版本"], 1)


if __name__ == "__main__":
    unittest.main()
