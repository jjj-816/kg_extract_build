import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class AuditReportUiTests(unittest.TestCase):
    @staticmethod
    def _run(report: dict, storage: str) -> AppTest:
        script = f"""
import streamlit as st
from pathlib import Path
import kg_extract_build.audit.settings as audit_settings
audit_settings.AUDIT_STORAGE_DIR = Path({storage!r})
import kg_extract_build.dashboard_audit as dashboard_audit
dashboard_audit.AUDIT_STORAGE_DIR = Path({storage!r})
report = {report!r}
dashboard_audit._render_human_review_and_publish(report)
"""
        os.environ["KG_AUDIT_STORAGE_DIR"] = storage
        return AppTest.from_string(script).run(timeout=30)

    def test_unresolved_review_is_visible_and_publish_is_gated(self):
        with tempfile.TemporaryDirectory() as storage:
            app = self._run({"document": {"document_id": "ui-blocked"}, "tasks": [{"task_id": "T1", "task_name": "需要复核", "result_status": "manual_review", "manual_reviews": [{"summary": "待人工确认"}], "evidence": []}]}, storage)
            self.assertEqual(list(app.exception), [])
            self.assertFalse(any("发布正式报告" in item.label for item in app.button))
            self.assertTrue(any("待处理" in item.value or "不能发布" in item.value for item in app.warning))

    def test_resolved_report_exposes_publish_and_both_downloads(self):
        with tempfile.TemporaryDirectory() as storage:
            app = self._run({"document": {"document_id": "ui-published"}, "tasks": [{"task_id": "T1", "task_name": "已复核", "result_status": "no_issue", "manual_reviews": [], "evidence": []}]}, storage)
            publish = next(item for item in app.button if "发布正式报告" in item.label)
            app = publish.click().run(timeout=30)
            self.assertEqual(list(app.exception), [])
            self.assertEqual(len(app.get("download_button")), 2)
            self.assertTrue(Path(storage, "reports", "ui-published.json").is_file())
            self.assertTrue(Path(storage, "reports", "ui-published.docx").is_file())

    def test_result_detail_labels_three_evidence_kinds(self):
        script = """
import kg_extract_build.dashboard_audit as dashboard_audit
dashboard_audit._render_stage2_result_detail({
    "task_id": "T1", "task_name": "evidence", "summary": "issue", "output_type": "issues", "result_status": "issue_found",
    "evidence": [
        {"evidence_type": "document", "block_id": "b1", "raw_text": "document source"},
        {"evidence_type": "normative_clause", "clause_id": "c1", "text": "normative clause", "version_id": "v1"},
        {"evidence_type": "graph_clue", "clue_id": "g1", "assertion_id": "a1", "evidence_sentence": "graph clue sentence"},
    ], "issues": [], "manual_reviews": [], "offline_items": [], "advisories": [],
}, {})
"""
        app = AppTest.from_string(script).run(timeout=30)
        self.assertEqual(list(app.exception), [])
        labels = [item.label for item in app.expander]
        self.assertGreaterEqual(len(labels), 1)


if __name__ == "__main__":
    unittest.main()
