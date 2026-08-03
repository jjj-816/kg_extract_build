import unittest
from types import SimpleNamespace

from kg_extract_build.audit.executor import AuditOrchestrator
from kg_extract_build.audit.models import (
    AuditDocumentBlock, ParsedAuditDocument, StoredAuditDocument, TaskEvidenceGroup, TaskLocationResult,
)
from kg_extract_build.audit.reporting import build_draft_report
from kg_extract_build.audit.task_library import load_published_task_library
from kg_extract_build.audit.word_parser import normalize_for_match


def _block(block_id: str, text: str, ordinal: int, images=()):
    return AuditDocumentBlock(block_id, "doc", ordinal, "paragraph", ("章节",), f"word/body[{ordinal}]/paragraph", text, normalize_for_match(text), image_refs=images)


class AuditExecutorTests(unittest.TestCase):
    def _preview(self):
        library = load_published_task_library()
        selected = tuple(library.task_by_id(task_id) for task_id in ("COVER-001", "APPC-002", "BASIS-003", "PREP-001"))
        blocks = (_block("cover", "", 1, ("cover-image",)), _block("body", "已有原文证据", 2))
        document = StoredAuditDocument("doc", "方案.docx", "docx", "a" * 64, None, "")
        parsed = ParsedAuditDocument(document, blocks, 2, 0, 1, True)
        group = TaskEvidenceGroup("g", "body", ("body",), ("章节",), (), 1, "test")
        cover_group = TaskEvidenceGroup("cover", "cover", ("cover",), ("封面",), (), 1, "test")
        locations = {
            "COVER-001": TaskLocationResult("COVER-001", "located", evidence_groups=(cover_group,)),
            "APPC-002": TaskLocationResult("APPC-002", "located", evidence_groups=(group,)),
            "BASIS-003": TaskLocationResult("BASIS-003", "located", evidence_groups=(group,)),
            "PREP-001": TaskLocationResult("PREP-001", "located", evidence_groups=(group,)),
        }
        return SimpleNamespace(parsed_document=parsed, task_library=SimpleNamespace(tasks=selected, task_library_id=library.task_library_id, version=library.version, sha256=library.sha256), locations=locations)

    def test_executes_stage_two_routes_without_defaulting_future_semantic_routes_to_pass(self):
        preview = self._preview()
        results = {result.task_id: result for result in AuditOrchestrator().execute_preview(preview)}

        self.assertEqual(results["COVER-001"].result_status, "manual_review")
        self.assertEqual(results["APPC-002"].result_status, "offline_completion")
        self.assertEqual(results["BASIS-003"].result_status, "no_issue")
        self.assertEqual(results["PREP-001"].execution_status, "pending")
        self.assertIsNone(results["PREP-001"].result_status)

    def test_draft_report_preserves_evidence_and_pending_status(self):
        preview = self._preview()
        results = AuditOrchestrator().execute_preview(preview)
        report = build_draft_report(preview, results)

        self.assertEqual(report["summary"]["task_count"], 4)
        pending = next(item for item in report["tasks"] if item["task_id"] == "PREP-001")
        self.assertEqual(pending["execution_status"], "pending")
        self.assertEqual(pending["result_status"], None)
        self.assertTrue(next(item for item in report["tasks"] if item["task_id"] == "BASIS-003")["evidence"])

    def test_deterministic_table_rule_aggregates_missing_business_fields(self):
        library = load_published_task_library()
        task = library.task_by_id("PREP-004")
        table = AuditDocumentBlock("table", "doc", 1, "table", ("第三章",), "word/body[1]/table[1]", "名称 | 单位 | 数量\n灭火器 | 具 | ", "", table_json={"rows": [["名称", "单位", "数量"], ["灭火器", "具", ""]]})
        parsed = ParsedAuditDocument(StoredAuditDocument("doc", "方案.docx", "docx", "a" * 64, None, ""), (table,), 0, 1, 0, False)
        group = TaskEvidenceGroup("g", "table", ("table",), ("第三章",), (), 1, "test")
        preview = SimpleNamespace(parsed_document=parsed, task_library=SimpleNamespace(tasks=(task,), task_library_id=library.task_library_id, version=library.version, sha256=library.sha256), locations={task.task_id: TaskLocationResult(task.task_id, "located", evidence_groups=(group,))})

        result = AuditOrchestrator().execute_preview(preview)[0]
        self.assertEqual(result.result_status, "issue_found")
        self.assertIn("数量", result.issues[0].summary)


if __name__ == "__main__":
    unittest.main()
