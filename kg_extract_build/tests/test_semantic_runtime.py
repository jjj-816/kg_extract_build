import unittest

from kg_extract_build.audit.models import AuditTaskDefinition
from kg_extract_build.audit.semantic_runtime import (
    EvidencePackage,
    SemanticRuntime,
    StructuredOutputError,
)


def task(route="semantic_compliance"):
    return AuditTaskDefinition(
        "T-1", 1, "section", "task", "content_semantic", route, None,
        "document", ("section",), ("field",), ("check",),
        ("document",), ("issue",), "electronic_submission", "all",
    )


class SemanticRuntimeTests(unittest.TestCase):
    def test_evidence_package_is_frozen_and_has_stable_id(self):
        evidence = ({"block_id": "b1", "raw_text": "text"},)
        package = EvidencePackage.from_task(task(), evidence, run_id="run-1")

        self.assertEqual(package.package_id, EvidencePackage.from_task(task(), evidence, "run-1").package_id)
        with self.assertRaises(TypeError):
            package.evidence[0]["raw_text"] = "changed"

    def test_invalid_model_output_is_corrected_once_then_isolated(self):
        calls = []

        def model(_task, _package, correction=False):
            calls.append(correction)
            return {"bad": True}

        result = SemanticRuntime(model=model).run(task(), [{"block_id": "b1"}], "run-1")

        self.assertEqual(calls, [False, True])
        self.assertEqual(result.execution_status, "failed")
        self.assertEqual(result.result_status, None)
        self.assertIn("结构化", result.diagnostics[0])

    def test_valid_model_output_is_returned_with_package_id(self):
        def model(_task, package, correction=False):
            return {
                "package_id": package.package_id,
                "result_status": "no_issue",
                "issues": [],
            }

        result = SemanticRuntime(model=model).run(task(), [{"block_id": "b1"}], "run-1")

        self.assertEqual(result.execution_status, "completed")
        self.assertEqual(result.result_status, "no_issue")
        self.assertEqual(result.evidence[0]["block_id"], "b1")


if __name__ == "__main__":
    unittest.main()
