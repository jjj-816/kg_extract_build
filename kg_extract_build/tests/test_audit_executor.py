import unittest
from types import SimpleNamespace
from unittest.mock import patch

from kg_extract_build.audit.executor import AuditOrchestrator
from kg_extract_build.audit.models import (
    AuditDocumentBlock, ParsedAuditDocument, StoredAuditDocument, TaskEvidenceGroup, TaskLocationResult,
)
from kg_extract_build.audit.reporting import build_draft_report, build_stage2_result_export, stage2_result_groups
from kg_extract_build.audit.risk_catalog import RiskCatalogError, detect_work_codes, load_risk_catalog
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

    def test_stage2_result_groups_keep_output_types_and_failures_separate(self):
        report = {
            "tasks": [
                {"task_id": "A", "task_name": "任务 A", "issues": [{"summary": "发现问题"}], "manual_reviews": [], "offline_items": [], "advisories": [], "evidence": []},
                {"task_id": "B", "task_name": "任务 B", "issues": [], "manual_reviews": [{"summary": "人工核验"}], "offline_items": [], "advisories": [{"summary": "JSA 提示"}], "evidence": []},
                {"task_id": "C", "task_name": "任务 C", "issues": [], "manual_reviews": [], "offline_items": [{"summary": "线下审核"}], "advisories": [], "execution_status": "failed", "diagnostics": ["服务不可用"], "evidence": []},
            ]
        }
        groups = stage2_result_groups(report)

        self.assertEqual([item["summary"] for item in groups["issues"]], ["发现问题"])
        self.assertEqual([item["summary"] for item in groups["manual_reviews"]], ["人工核验"])
        self.assertEqual([item["summary"] for item in groups["offline_items"]], ["线下审核"])
        self.assertEqual([item["summary"] for item in groups["advisories"]], ["JSA 提示"])
        self.assertEqual(groups["system_errors"][0]["summary"], "服务不可用")

        export = build_stage2_result_export(report)
        self.assertEqual(export.columns.tolist(), ["结果类型", "任务 ID", "任务名称", "问题类别", "问题说明", "实际值", "期望值", "受影响范围", "来源章节", "处理建议"])
        self.assertEqual(export.loc[0, "结果类型"], "审核问题")

    def test_appd001_h25a_appendix_rows_only_report_missing_quantity(self):
        library = load_published_task_library()
        task = library.task_by_id("APPD-001")
        header = ["序号", "名称", "规格型号", "数量", "完好情况", "综合评价", "入场时间", "验收结果", "验收人"]
        equipment_names = ["灭火器", "气体检测仪", "发电机", "电焊机", "配电箱", "电镐", "电动扳手", "葫芦", "常用工具（扳手、锄头、铲子等）"]
        equipment_rows = [[str(index), name, "", "", "完好", "合格", "", "", ""] for index, name in enumerate(equipment_names, 1)]
        merged_note = "上述设备装置均评估合格。注：设备需张贴目视化合格标志。检查人（签字）：施工单位（盖章）：年 月 日"
        rows = [header, *equipment_rows, [merged_note] * len(header), [""] * len(header), ["示例", "示例设备", "", "", "", "", "", "", ""]]
        table = AuditDocumentBlock("appd", "doc", 1, "table", ("附录D",), "word/body[1]/table[1]", "", "", table_json={"rows": rows})
        parsed = ParsedAuditDocument(StoredAuditDocument("doc", "方案.docx", "docx", "a" * 64, None, ""), (table,), 0, 1, 0, False)
        group = TaskEvidenceGroup("g", "appd", ("appd",), ("附录D",), (), 1, "test")
        preview = SimpleNamespace(parsed_document=parsed, task_library=SimpleNamespace(tasks=(task,), task_library_id=library.task_library_id, version=library.version, sha256=library.sha256), locations={task.task_id: TaskLocationResult(task.task_id, "located", evidence_groups=(group,))})

        result = AuditOrchestrator().execute_preview(preview)[0]

        self.assertEqual(task.required[:4], ("名称", "数量", "完好情况", "综合评价"))
        self.assertEqual(result.result_status, "issue_found")
        self.assertEqual(len(result.issues), 1)
        self.assertEqual(result.issues[0].affected_scope, "数量")
        self.assertNotIn("规格型号", result.issues[0].summary)
        self.assertNotIn("完好", result.issues[0].summary)
        self.assertNotIn("综合", result.issues[0].summary)

    def test_arr001_uses_preconfirmed_detection_without_rechecking_manual_types(self):
        library = load_published_task_library()
        task = library.task_by_id("ARR-001")
        paragraph = _block("arr", "风险作业目录编号：CN-TY-A05、CN-TY-B01", 1)
        parsed = ParsedAuditDocument(StoredAuditDocument("doc", "方案.docx", "docx", "a" * 64, None, ""), (paragraph,), 1, 0, 0, False)
        group = TaskEvidenceGroup("g", "arr", ("arr",), ("第四章",), (), 1, "test")
        preview = SimpleNamespace(parsed_document=parsed, task_library=SimpleNamespace(tasks=(task,), task_library_id=library.task_library_id, version=library.version, sha256=library.sha256), locations={task.task_id: TaskLocationResult(task.task_id, "located", evidence_groups=(group,))})
        context = {
            "detected_work_codes": [
                {"code": "CN-TY-A05", "catalog_match_status": "matched", "work_types": ["动火作业"]},
                {"code": "CN-TY-B01", "catalog_match_status": "matched", "work_types": ["动土作业"]},
            ],
            "detected_work_types": ["动火作业", "动土作业"],
            "confirmed_work_types": ["动火作业"],
            "work_types": ["动火作业"],
            "work_type_adjustments": {"removed": ["动土作业"], "added": []},
        }
        passed = AuditOrchestrator().execute_preview(preview, context)[0]
        self.assertEqual(passed.result_status, "no_issue")

    def test_arr001_catalog_configuration_error_is_system_failure(self):
        library = load_published_task_library()
        task = library.task_by_id("ARR-001")
        paragraph = _block("arr", "风险作业目录编号：CN-TY-A05", 1)
        parsed = ParsedAuditDocument(StoredAuditDocument("doc", "方案.docx", "docx", "a" * 64, None, ""), (paragraph,), 1, 0, 0, False)
        group = TaskEvidenceGroup("g", "arr", ("arr",), ("第四章",), (), 1, "test")
        preview = SimpleNamespace(parsed_document=parsed, task_library=SimpleNamespace(tasks=(task,), task_library_id=library.task_library_id, version=library.version, sha256=library.sha256), locations={task.task_id: TaskLocationResult(task.task_id, "located", evidence_groups=(group,))})

        with patch("kg_extract_build.audit.executor.detect_work_codes", side_effect=RiskCatalogError("目录不可用")):
            result = AuditOrchestrator().execute_preview(preview, {"work_types": ["动火作业"]})[0]

        self.assertEqual(result.execution_status, "failed")
        self.assertIn("目录配置错误", result.diagnostics[0])

    def test_arr001_allows_explicit_no_risk_work_and_requires_unmatched_confirmation(self):
        library = load_published_task_library()
        task = library.task_by_id("ARR-001")
        group = TaskEvidenceGroup("g", "arr", ("arr",), ("第四章",), (), 1, "test")
        def run(text, context=None):
            paragraph = _block("arr", text, 1)
            parsed = ParsedAuditDocument(StoredAuditDocument("doc", "方案.docx", "docx", "a" * 64, None, ""), (paragraph,), 1, 0, 0, False)
            preview = SimpleNamespace(parsed_document=parsed, task_library=SimpleNamespace(tasks=(task,), task_library_id=library.task_library_id, version=library.version, sha256=library.sha256), locations={task.task_id: TaskLocationResult(task.task_id, "located", evidence_groups=(group,))})
            with patch("kg_extract_build.audit.executor.detect_work_codes", return_value=()):
                return AuditOrchestrator().execute_preview(preview, context)[0]

        self.assertEqual(run("风险作业目录编号：不涉及风险作业").result_status, "no_issue")
        self.assertIn("未填写编号", run("风险作业目录编号：").issues[0].summary)
        unmatched = {"detected_work_codes": [{"code": "CN-UNKNOWN-A01", "catalog_match_status": "unmatched", "work_types": []}]}
        self.assertEqual(run("风险作业目录编号：CN-UNKNOWN-A01", unmatched).result_status, "manual_review")
        self.assertEqual(run("风险作业目录编号：CN-UNKNOWN-A01", {**unmatched, "unmatched_codes_confirmed": True}).result_status, "no_issue")

    def test_selected_scope_tasks_wait_for_confirmed_work_types(self):
        library = load_published_task_library()
        task = library.task_by_id("ARR-003")
        paragraph = _block("arr003", "施工重点与难点", 1)
        parsed = ParsedAuditDocument(StoredAuditDocument("doc", "方案.docx", "docx", "a" * 64, None, ""), (paragraph,), 1, 0, 0, False)
        group = TaskEvidenceGroup("g", "arr003", ("arr003",), ("第四章",), (), 1, "test")
        preview = SimpleNamespace(parsed_document=parsed, task_library=SimpleNamespace(tasks=(task,), task_library_id=library.task_library_id, version=library.version, sha256=library.sha256), locations={task.task_id: TaskLocationResult(task.task_id, "located", evidence_groups=(group,))})

        result = AuditOrchestrator().execute_preview(preview, {"confirmed_work_types": []})[0]

        self.assertEqual(result.execution_status, "pending")
        self.assertIn("暂不启用", result.diagnostics[0])

    def test_project_risk_catalog_loads_known_codes(self):
        catalog = load_risk_catalog()
        self.assertEqual(catalog.work_types_for("CN-TY-A05"), frozenset({"动火作业"}))
        self.assertEqual(catalog.work_types_for("CN-TY-B01"), frozenset({"动土作业"}))
        self.assertEqual(catalog.work_types_for("CN-TXZK-C09"), frozenset({"上位系统类作业"}))
        detected = detect_work_codes((_block("arr", "风险作业目录编号：CN-TY-A05、CN-TY-B01、CN-TXZK-C09", 7),), catalog)
        self.assertEqual([item.code for item in detected], ["CN-TY-A05", "CN-TY-B01", "CN-TXZK-C09"])
        self.assertEqual(detected[2].work_types, ("上位系统类作业",))
        self.assertEqual(detected[0].source_locator, "word/body[7]/paragraph")

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
