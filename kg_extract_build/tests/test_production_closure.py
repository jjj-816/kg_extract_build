import json
import tempfile
import unittest
from pathlib import Path

from docx import Document

from kg_extract_build.audit.bounded_graph import GraphClue, GraphRetrievalResult
from kg_extract_build.audit.reasonableness import ReasonablenessRuntime
from kg_extract_build.audit.report_service import append_review_action, create_correction_version, export_report_snapshot, freeze_report_snapshot
from kg_extract_build.audit.semantic_runtime import SemanticRuntime
from kg_extract_build.audit.models import AuditTaskDefinition


class ProductionClosureTests(unittest.TestCase):
    def test_review_publish_correct_and_export_path(self):
        report = {"report_type": "audit_draft_v1", "document": {"document_id": "fixture"}, "tasks": [{"task_id": "SEM-1", "task_name": "语义任务", "execution_status": "completed", "result_status": "manual_review", "manual_reviews": [{"summary": "需确认"}], "issues": [], "offline_items": [], "advisories": [], "evidence": [{"block_id": "d1"}]}]}
        reviewed = append_review_action(report, task_id="SEM-1", action="confirm", reviewer="qa", explanation="确认")
        first = freeze_report_snapshot(reviewed, publisher="qa")
        first["report_id"] = "report-1"
        first["version"] = 1
        first["source_snapshot"] = {"document_hash": "doc-hash", "evidence_hash": "evidence-hash"}
        with tempfile.TemporaryDirectory() as directory:
            json_path, docx_path = export_report_snapshot(first, directory)
            exported = json.loads(json_path.read_text(encoding="utf-8"))
            docx_text = "\n".join(paragraph.text for paragraph in Document(str(docx_path)).paragraphs)
            self.assertEqual(exported["tasks"][0]["task_id"], "SEM-1")
            self.assertIn("SEM-1", docx_text)
        second = create_correction_version(first, changes=[{"task_id": "SEM-1", "result_status": "no_issue"}], reason="复核更正", source_snapshot=first["source_snapshot"])
        self.assertEqual(second["previous_report_id"], "report-1")
        self.assertEqual(first["tasks"][0]["result_status"], "manual_review")

    def test_local_semantic_failure_and_graph_degradation_are_isolated(self):
        task = AuditTaskDefinition("SEM-1", 1, "s", "语义", "content_semantic", "semantic_compliance", None, "document", (), (), (), (), (), "stage", "all")
        runtime = SemanticRuntime(model=lambda *_args, **_kwargs: {"invalid": True})
        failed = runtime.run(task, [{"block_id": "d1"}], "run-1")
        self.assertEqual(failed.execution_status, "failed")
        graph_task = AuditTaskDefinition("R-1", 2, "s", "合理性", "content_semantic", "semantic_reasonableness", None, "document", (), (), (), (), (), "stage", "all")
        degraded = ReasonablenessRuntime().run(graph_task, [{"block_id": "d2"}], GraphRetrievalResult((), True, "图服务不可用"), "run-1")
        self.assertEqual(degraded.execution_status, "failed")
        self.assertIsNone(degraded.result_status)


if __name__ == "__main__":
    unittest.main()
