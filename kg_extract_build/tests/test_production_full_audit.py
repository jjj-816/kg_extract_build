import unittest
from types import SimpleNamespace
from unittest.mock import patch

from kg_extract_build.audit.executor import AuditOrchestrator, TaskExecutionResult
from kg_extract_build.audit.models import AuditDocumentBlock, ParsedAuditDocument, StoredAuditDocument, TaskLocationResult
from kg_extract_build.audit.normative_scope import NormativeScope, NormativeScopePreflight
from kg_extract_build.audit.production_composition import ProductionAuditComposition
from kg_extract_build.audit.reporting import build_draft_report
from kg_extract_build.audit.task_library import load_published_task_library


class ProductionFullAuditTests(unittest.TestCase):
    def test_all_published_tasks_get_isolated_execution_records(self):
        library = load_published_task_library()
        parsed = ParsedAuditDocument(
            StoredAuditDocument("doc-full", "full.docx", "docx", "a" * 64, None, ""),
            (AuditDocumentBlock("b1", "doc-full", 1, "paragraph", (), "body[1]", "", ""),),
            1, 0, 0, False,
        )
        locations = {task.task_id: TaskLocationResult(task.task_id, "not_located") for task in library.tasks}
        preview = SimpleNamespace(parsed_document=parsed, task_library=library, locations=locations)
        blocked = NormativeScopePreflight(NormativeScope.freeze(2025, ("missing",), ()), (), True, ("normative coverage missing",))
        composition = ProductionAuditComposition.build(
            normative_search=lambda **kwargs: {"evidence": [], "coverage": []},
            compliance_model=lambda *args: {"result_status": "no_issue", "issues": []},
            reasonableness_model=None,
            graph=None,
            graph_queries={task.task_id: {"query": task.name, "relationship_types": ("USES",), "max_hops": 2} for task in library.tasks if task.route == "semantic_reasonableness"},
            config_snapshot={"prompt_version": "test"},
            scope_preflight=blocked,
        )
        with patch("kg_extract_build.audit.executor.execute_jsa_advisory", side_effect=lambda task, parsed, run_id, previous: TaskExecutionResult(task.task_id, task.route, "completed", "manual_review", ())):
            results = AuditOrchestrator().execute_preview(preview, {**composition.as_audit_context(), "confirmed_work_types": ("selected",)}, run_id="full-test")
        report = build_draft_report(preview, results)
        self.assertEqual(len(results), len(library.tasks))
        self.assertEqual(report["summary"]["task_count"], len(library.tasks))
        self.assertEqual({item["task_id"] for item in report["tasks"]}, {task.task_id for task in library.tasks})
        self.assertTrue(all("execution_status" in item for item in report["tasks"]))


if __name__ == "__main__":
    unittest.main()
