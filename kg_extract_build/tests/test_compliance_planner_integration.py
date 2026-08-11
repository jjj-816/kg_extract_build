import unittest
from types import SimpleNamespace

from kg_extract_build.audit.compliance_runtime import ComplianceRuntime
from kg_extract_build.audit.normative_scope import NormativeScope, NormativeScopePreflight


class CompliancePlannerIntegrationTests(unittest.TestCase):
    def test_planned_query_is_used_for_normative_recall(self):
        seen = []
        preflight = NormativeScopePreflight(NormativeScope.freeze(2025, ("f1",), ()), ({"family_id": "f1", "coverage_status": "covered"},), False, ())
        class Planner:
            def plan(self, task, evidence):
                return SimpleNamespace(normative_queries=("planned query",), diagnostics=("plan=v1",))
        def search(**kwargs):
            seen.append(kwargs["query"])
            return {"evidence": [{"clause_id": "c1", "version_id": "v1", "release_id": "r1", "text": "完整条款", "source_type": "spec"}], "coverage": []}
        task = SimpleNamespace(task_id="BASIS-002", route="semantic_compliance", name="task")
        runtime = ComplianceRuntime(search, lambda *_: {"result_status": "no_issue", "document_evidence_ids": ["d1"], "normative_evidence_ids": ["c1"], "issues": []}, planner=Planner())
        result = runtime.run(task, [{"block_id": "d1", "raw_text": "原始方案"}], scope_preflight=preflight, run_id="r")
        self.assertEqual(seen, ["planned query"])
        self.assertIn("plan=v1", result.diagnostics)


if __name__ == "__main__":
    unittest.main()
