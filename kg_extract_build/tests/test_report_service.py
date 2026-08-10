import tempfile
import unittest
from pathlib import Path

from kg_extract_build.audit.report_service import ReportPublishBlocked, ReportReauditRequired, append_review_action, create_correction_version, export_report_snapshot, freeze_report_snapshot


def report():
    return {"document": {"document_id": "doc-1"}, "tasks": [{"task_id": "T1", "task_name": "任务", "result_status": "manual_review", "manual_reviews": [{"summary": "需核验"}], "issues": [], "offline_items": [], "advisories": [], "evidence": []}]}


class ReportServiceTests(unittest.TestCase):
    def test_unresolved_manual_item_blocks_publication(self):
        with self.assertRaises(ReportPublishBlocked):
            freeze_report_snapshot(report(), publisher="reviewer")

    def test_review_and_exports_share_one_snapshot(self):
        reviewed = append_review_action(report(), task_id="T1", action="confirm", reviewer="reviewer", explanation="已确认")
        snapshot = freeze_report_snapshot(reviewed, publisher="reviewer")
        with tempfile.TemporaryDirectory() as directory:
            json_path, docx_path = export_report_snapshot(snapshot, directory)
            self.assertTrue(json_path.is_file() and docx_path.is_file())
            self.assertEqual(snapshot["publication"]["publisher"], "reviewer")
            self.assertIn("snapshot_sha256", json_path.read_text(encoding="utf-8"))

    def test_correction_creates_new_version_and_preserves_previous(self):
        source = {"document_hash": "h1", "evidence_hash": "e1"}
        previous = {"report_id": "r1", "version": 1, "source_snapshot": source, "tasks": [{"task_id": "T1", "result_status": "manual_review"}]}
        corrected = create_correction_version(previous, changes=[{"task_id": "T1", "result_status": "no_issue"}], reason="人工更正", source_snapshot=source)
        self.assertEqual(corrected["version"], 2)
        self.assertEqual(corrected["previous_report_id"], "r1")
        self.assertEqual(previous["tasks"][0]["result_status"], "manual_review")

    def test_changed_source_requires_new_audit(self):
        previous = {"source_snapshot": {"document_hash": "h1"}}
        with self.assertRaises(ReportReauditRequired):
            create_correction_version(previous, changes=[], reason="x", source_snapshot={"document_hash": "h2"})


if __name__ == "__main__":
    unittest.main()
