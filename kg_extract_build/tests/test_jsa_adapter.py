import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kg_extract_build.audit.executor import AuditOrchestrator
from kg_extract_build.audit.jsa_adapter import JSAAdapterError, JSAAuditResponse, audit_jsa, build_jsa_request
from kg_extract_build.audit.models import AuditDocumentBlock, ParsedAuditDocument, StoredAuditDocument, TaskEvidenceGroup, TaskLocationResult
from kg_extract_build.audit.reporting import build_draft_report, build_stage2_result_export
from kg_extract_build.audit.task_library import load_published_task_library


def _preview(task_ids=("ARR-002", "HSE-001", "HSE-002")):
    library = load_published_task_library()
    steps = AuditDocumentBlock(
        "steps", "doc", 1, "table", ("4.1 施工顺序",), "word/body[10]/table[1]",
        "步骤\n电缆沟开挖", "", table_json={"rows": [["步骤"], ["电缆沟开挖"]]},
    )
    jsa = AuditDocumentBlock(
        "jsa", "doc", 2, "table", ("5.1 JSA",), "word/body[20]/table[1]",
        "作业活动步骤 | 危害 | 风险等级 | 控制措施\n电缆沟开挖 | 损坏地下管线 | 中 | ", "",
        table_json={"rows": [["作业活动步骤", "危害", "风险等级", "控制措施"], ["电缆沟开挖", "损坏地下管线", "中", ""]]},
    )
    parsed = ParsedAuditDocument(StoredAuditDocument("doc", "H25A.docx", "docx", "a" * 64, None, ""), (steps, jsa), 0, 2, 0, False)
    step_group = TaskEvidenceGroup("steps", "steps", ("steps",), ("4.1 施工顺序",), (), 1, "test")
    jsa_group = TaskEvidenceGroup("jsa", "jsa", ("jsa",), ("5.1 JSA",), (), 1, "test")
    locations = {
        "ARR-002": TaskLocationResult("ARR-002", "located", evidence_groups=(step_group,)),
        "HSE-001": TaskLocationResult("HSE-001", "located", evidence_groups=(jsa_group,)),
        "HSE-002": TaskLocationResult("HSE-002", "located", evidence_groups=(jsa_group,)),
    }
    tasks = tuple(library.task_by_id(task_id) for task_id in task_ids)
    return SimpleNamespace(parsed_document=parsed, task_library=SimpleNamespace(tasks=tasks, task_library_id=library.task_library_id, version=library.version, sha256=library.sha256), locations=locations)


class JSAAdapterTests(unittest.TestCase):
    def test_builds_request_from_already_parsed_evidence(self):
        payload = build_jsa_request(_preview(), "run-1")
        self.assertEqual(payload["construction_steps"][0]["step"], "电缆沟开挖")
        self.assertEqual(payload["jsa_rows"][0]["hazard"], "损坏地下管线")
        self.assertEqual(payload["jsa_rows"][0]["source_locator"], "word/body[20]/table[1]/row[2]")

    def test_excludes_risk_catalog_number_from_construction_steps(self):
        preview = _preview()
        catalog_text = AuditDocumentBlock("catalog", "doc", 3, "paragraph", ("第四章",), "word/body[11]/paragraph", "风险作业目录编号：CN-TY-A05、CN-TY-B01", "")
        preview.parsed_document = ParsedAuditDocument(preview.parsed_document.document, (*preview.parsed_document.blocks, catalog_text), 1, 2, 0, False)
        group = TaskEvidenceGroup("steps", "steps", ("steps", "catalog"), ("4.1 施工顺序",), (), 1, "test")
        preview.locations["ARR-002"] = TaskLocationResult("ARR-002", "located", evidence_groups=(group,))
        payload = build_jsa_request(preview, "run-filter")
        self.assertEqual([item["step"] for item in payload["construction_steps"]], ["电缆沟开挖"])

    def test_splits_construction_order_chain_into_atomic_steps(self):
        preview = _preview()
        chain = AuditDocumentBlock("chain", "doc", 3, "paragraph", ("4.1 施工顺序",), "word/body[11]/paragraph", "施工顺序安排：开工条件确认→安全技术交底→电缆敷设", "")
        preview.parsed_document = ParsedAuditDocument(preview.parsed_document.document, (*preview.parsed_document.blocks, chain), 1, 2, 0, False)
        group = TaskEvidenceGroup("chain", "chain", ("chain",), ("4.1 施工顺序",), (), 1, "test")
        preview.locations["ARR-002"] = TaskLocationResult("ARR-002", "located", evidence_groups=(group,))
        payload = build_jsa_request(preview, "run-chain")
        self.assertEqual([item["step"] for item in payload["construction_steps"]], ["开工条件确认", "安全技术交底", "电缆敷设"])

    @patch("kg_extract_build.audit.jsa_adapter.requests.post")
    def test_calls_json_only_readonly_endpoint(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {"engine_version": "jsa-readonly-v1", "suggestions": [], "diagnostics": []}
        post.return_value = response
        audit_jsa(_preview(), "run-2")
        self.assertEqual(post.call_args.kwargs["json"]["run_id"], "run-2")
        self.assertIn("construction_steps", post.call_args.kwargs["json"])

    @patch("kg_extract_build.audit.executor.audit_jsa")
    def test_hse002_keeps_suggestions_out_of_normal_issues(self, readonly_audit):
        readonly_audit.return_value = JSAAuditResponse("jsa-readonly-v1", ({
            "kind": "missing_hazard_group", "step": "电缆沟开挖", "total_missing_hazards": 10,
            "returned_hazards": 8, "truncated": True, "basis": "风险库匹配", "source_locator": "word/body[20]/table[1]/row[2]",
            "candidates": [{"hazard": f"危害{number}", "control_measure": f"措施{number}", "risk_level": "中", "similarity": 1.0} for number in range(8)],
        },), ())
        results = AuditOrchestrator().execute_preview(_preview(), {"confirmed_work_types": ["动火作业"]}, run_id="run-3")
        result = {item.task_id: item for item in results}["HSE-002"]
        self.assertEqual(result.result_status, "no_issue")
        self.assertFalse(result.issues)
        self.assertEqual(len(result.advisories), 1)
        self.assertEqual(result.advisories[0].candidate_total, 10)
        self.assertEqual(len(result.advisories[0].candidate_rows), 8)
        self.assertTrue(result.advisories[0].candidate_truncated)
        report = build_draft_report(_preview(), results)
        exported = build_stage2_result_export(report)
        advisory = exported[exported["结果类型"] == "JSA 提示项"].iloc[0]
        self.assertEqual(len(exported[exported["结果类型"] == "JSA 提示项"]), 8)
        self.assertEqual(advisory["候选总数"], 10)
        self.assertEqual(advisory["展示序号"], 1)

    @patch("kg_extract_build.audit.executor.audit_jsa")
    def test_hse002_separates_missing_jsa_step_from_hazard_candidates(self, readonly_audit):
        readonly_audit.return_value = JSAAuditResponse("jsa-readonly-v2", (
            {"kind": "missing_jsa_step", "step": "安全技术交底", "basis": "JSA 未覆盖", "source_locator": "word/body[11]/paragraph"},
            {"kind": "missing_hazard_group", "step": "安全技术交底", "total_missing_hazards": 1, "returned_hazards": 1, "truncated": False, "basis": "风险库匹配", "source_locator": "word/body[11]/paragraph", "candidates": [{"hazard": "触电", "control_measure": "设置监护", "risk_level": "中", "similarity": 1.0}]},
        ), ())
        result = {item.task_id: item for item in AuditOrchestrator().execute_preview(_preview(), {"confirmed_work_types": ["动火作业"]}, run_id="run-steps")}["HSE-002"]
        self.assertEqual(len(result.advisories), 2)
        self.assertEqual(result.advisories[0].category, "JSA 步骤覆盖建议")
        self.assertEqual(result.advisories[1].category, "JSA 补充建议")
        self.assertEqual(result.advisories[1].candidate_rows[0]["hazard"], "触电")

    @patch("kg_extract_build.audit.executor.audit_jsa", side_effect=JSAAdapterError("服务不可用"))
    def test_hse002_records_service_failure_as_system_error(self, _readonly_audit):
        result = {item.task_id: item for item in AuditOrchestrator().execute_preview(_preview(), {"confirmed_work_types": ["动火作业"]}, run_id="run-4")}["HSE-002"]
        self.assertEqual(result.execution_status, "failed")
        self.assertIsNone(result.result_status)
        self.assertIn("服务不可用", result.diagnostics[0])


if __name__ == "__main__":
    unittest.main()
