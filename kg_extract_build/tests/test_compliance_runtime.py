import unittest
from types import SimpleNamespace

from kg_extract_build.audit.compliance_runtime import ComplianceRuntime
from kg_extract_build.audit.models import AuditTaskDefinition
from kg_extract_build.audit.normative_scope import NormativeScope, NormativeScopePreflight
from kg_extract_build.audit.retrieval_planner import RetrievalPlan
from kg_extract_build.audit.semantic_compliance import filter_clause_candidates


TASK = AuditTaskDefinition("C-1", 1, "s", "合规", "content_semantic", "semantic_compliance", None, "document", (), (), (), (), (), "stage", "all")


def preflight(blocked=False):
    scope = NormativeScope.freeze(2025, ["f1"], [])
    return NormativeScopePreflight(scope, (), blocked, ("覆盖不足",) if blocked else ())


def eligible_version_fields():
    return {
        "metadata_confirmed": True,
        "version_status": "effective",
        "index_status": "ready",
        "effective_year": 2020,
        "invalid_year": None,
    }


class ComplianceRuntimeTests(unittest.TestCase):
    def test_uncovered_declared_norm_is_advisory_and_does_not_skip_retrieval(self):
        declared = "《未索引规范》GB00000-2000"
        scope = NormativeScope.freeze(2025, [declared], [])
        scope_preflight = NormativeScopePreflight(
            scope,
            ({"family_id": declared, "coverage_status": "uncovered"},),
            False,
            ("规范覆盖不足",),
        )

        result = ComplianceRuntime(
            lambda **_: {"coverage": [{"coverage_status": "uncovered"}], "evidence": [{
                "clause_id": "c1", "version_id": "GB00000-2000", "release_id": "rel",
                "text": "完整条款", "source_type": "spec", "standard_code": "GB00000-2000", **eligible_version_fields(),
            }]},
            lambda *_: {"result_status": "no_issue", "document_evidence_ids": [], "normative_evidence_ids": [], "issues": []},
        ).run(TASK, [{"block_id": "d1", "raw_text": "内容"}], scope_preflight=scope_preflight, run_id="r")

        stages = {item["stage"]: item for item in result.execution_trace}
        self.assertEqual(stages["applicability_preflight"]["status"], "advisory")
        self.assertEqual(stages["normative_retrieval"]["status"], "completed")

    def test_candidate_trace_explains_declared_norm_filtering(self):
        declared = "《页岩气地面工程设计规范》Q/SY1858-2015"
        scope_preflight = NormativeScopePreflight(NormativeScope.freeze(2025, [declared], []), (), False, ())
        result = ComplianceRuntime(
            lambda **_: {"evidence": [
                {"clause_id": "c1", "version_id": "Q/SY1858-2015", "release_id": "rel", "text": "条款一", "source_type": "spec", **eligible_version_fields()},
                {"clause_id": "c2", "version_id": "GB50183-2004", "release_id": "rel", "text": "条款二", "source_type": "spec", **eligible_version_fields()},
            ]},
            lambda *_: {"result_status": "no_issue", "document_evidence_ids": [], "normative_evidence_ids": [], "issues": []},
        ).run(TASK, [{"block_id": "d1", "raw_text": "内容"}], scope_preflight=scope_preflight, run_id="r")

        retrieval = next(item for item in result.execution_trace if item["stage"] == "normative_retrieval" and item["status"] != "started")
        trace = retrieval["output"]["candidates"]
        self.assertEqual(trace[0]["selection"], "selected")
        self.assertEqual(trace[1]["selection"], "filtered")
        self.assertEqual(trace[1]["filter_reason"], "not_declared_norm")
        self.assertIn("declared_norm_omission", retrieval["output"]["warnings"])

    def test_candidate_trace_records_each_terminal_filter_reason(self):
        scope = NormativeScope.freeze(2025, ["GB00000-2000"], [])
        selected, trace, warnings = filter_clause_candidates({"evidence": [
            {"clause_id": "invalid", "version_id": "GB00000-2000", "release_id": "rel", "text": "x", "source_type": "spec", "same_year_version_conflict": True, **eligible_version_fields()},
            {"clause_id": "chain", "version_id": "GB00000-2000", "release_id": "rel", "text": "x", "source_type": "spec", "substitute_chain_valid": False, **eligible_version_fields()},
            {"clause_id": "partial", "version_id": "GB00000-2000", "release_id": "rel", "text": "", "source_type": "spec", **eligible_version_fields()},
            {"clause_id": "inapplicable", "version_id": "GB00000-2000", "release_id": "rel", "text": "x", "source_type": "spec", "applicability": "not_applicable", **eligible_version_fields()},
        ]}, scope)

        self.assertEqual(selected, ())
        self.assertEqual([item["filter_reason"] for item in trace], [
            "invalid_version", "same_year_substitute_chain_invalid", "incomplete_clause", "not_applicable",
        ])
        self.assertEqual(warnings, ())

    def test_only_confirmed_effective_enabled_indexed_candidate_enters_evidence_package(self):
        scope = NormativeScope.freeze(2025, ["GB00000-2000"], [])
        valid = {
            "version_id": "GB00000-2000", "release_id": "rel", "text": "x", "source_type": "spec",
            **eligible_version_fields(),
        }
        rejected = [
            ("published", {"version_status": "published"}),
            ("missing_metadata", {"metadata_confirmed": None}),
            ("unconfirmed_metadata", {"metadata_confirmed": False}),
            ("index_not_ready", {"index_status": "building"}),
            ("audit_disabled", {"audit_disabled_at": "2025-01-01"}),
            ("not_yet_effective", {"effective_year": 2026}),
            ("expired", {"invalid_year": 2024}),
        ]
        evidence = [{"clause_id": "valid", **valid}]
        evidence.extend({"clause_id": clause_id, **valid, **override} for clause_id, override in rejected)

        selected, trace, _ = filter_clause_candidates({"evidence": evidence}, scope)

        self.assertEqual([item["clause_id"] for item in selected], ["valid"])
        self.assertEqual(
            {item["clause_id"] for item in trace if item["filter_reason"] == "invalid_version"},
            {clause_id for clause_id, _ in rejected},
        )

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
            return {"coverage": [{"coverage_status": "covered"}], "evidence": [{"clause_id": "c1", "version_id": "v1", "release_id": "rel", "text": "完整条款", "source_type": "spec", **eligible_version_fields()}]}
        def model(_task, package):
            return {"result_status": "issue_found", "document_evidence_ids": ["d1"], "normative_evidence_ids": ["c1"], "issues": [{"category": "规范不符合", "summary": "不符合", "machine_status": "open"}]}
        result = ComplianceRuntime(search, model).run(TASK, [{"block_id": "d1", "raw_text": "内容"}], scope_preflight=preflight(), run_id="r")
        self.assertEqual(result.result_status, "issue_found")
        self.assertEqual({item.get("evidence_type") for item in result.evidence}, {"document", "normative_clause"})


if __name__ == "__main__":
    unittest.main()
