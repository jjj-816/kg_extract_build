import unittest
from types import SimpleNamespace

from kg_extract_build.audit.compliance_runtime import ComplianceRuntime
from kg_extract_build.audit.models import AuditTaskDefinition
from kg_extract_build.audit.normative_scope import NormativeScope, NormativeScopePreflight
from kg_extract_build.audit.retrieval_planner import RetrievalPlan


TASK = AuditTaskDefinition("C-1", 1, "s", "合规", "content_semantic", "semantic_compliance", None, "document", (), (), (), (), (), "stage", "all")


def preflight(blocked=False):
    scope = NormativeScope.freeze(2025, ["f1"], [])
    return NormativeScopePreflight(scope, (), blocked, ("覆盖不足",) if blocked else ())


class ComplianceRuntimeTests(unittest.TestCase):
    def test_retrieval_planning_trace_includes_correction_responses(self):
        interaction = {
            "raw_response": "{\"invalid\": true}",
            "parsed_response": {},
            "correction_raw_response": "{\"graph_queries\": []}",
            "correction_parsed_response": {"graph_queries": []},
        }

        class Planner:
            model = SimpleNamespace(last_interaction=interaction)

            def plan(self, task, evidence):
                return RetrievalPlan(task.task_id, "v1", ("d1",), (), (), (), ())

        result = ComplianceRuntime(lambda **_: {}, lambda *_: {}, Planner()).run(
            TASK, [{"block_id": "d1", "raw_text": "内容"}], scope_preflight=preflight(), run_id="r",
        )

        planning = next(item for item in result.execution_trace if item["stage"] == "retrieval_planning")
        self.assertEqual(planning["output"]["correction_raw_response"], interaction["correction_raw_response"])
        self.assertEqual(planning["output"]["correction_parsed_response"], interaction["correction_parsed_response"])

    def test_coverage_gap_is_advisory_and_retrieval_still_runs(self):
        called = []
        runtime = ComplianceRuntime(lambda **_: called.append(True) or {}, lambda *_: {})
        result = runtime.run(TASK, [{"block_id": "d1", "raw_text": "内容"}], scope_preflight=preflight(True), run_id="r")
        self.assertEqual(result.result_status, "manual_review")
        self.assertEqual(called, [True])
        self.assertIn("规范检索未返回可用条款", result.diagnostics)

    def test_published_clause_supports_traceable_noncompliance(self):
        def search(**_):
            return {"coverage": [{"coverage_status": "covered"}], "evidence": [{"clause_id": "c1", "version_id": "v1", "release_id": "rel", "text": "完整条款", "source_type": "spec"}]}
        def model(_task, package):
            return {"result_status": "issue_found", "document_evidence_ids": ["d1"], "normative_evidence_ids": ["c1"], "issues": [{"category": "规范不符合", "summary": "不符合", "machine_status": "open"}]}
        result = ComplianceRuntime(search, model).run(TASK, [{"block_id": "d1", "raw_text": "内容"}], scope_preflight=preflight(), run_id="r")
        self.assertEqual(result.result_status, "issue_found")
        self.assertEqual({item.get("evidence_type") for item in result.evidence}, {"document", "normative_clause"})


if __name__ == "__main__":
    unittest.main()
