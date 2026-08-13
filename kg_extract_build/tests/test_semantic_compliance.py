import unittest
from types import SimpleNamespace

from kg_extract_build.audit.semantic_compliance import (
    filter_clause_candidates,
    normalize_compliance_conclusion,
    select_published_clause_evidence,
    validate_compliance_conclusion,
)
from kg_extract_build.audit.normative_scope import NormativeScope


def eligible_version_fields():
    return {
        "metadata_confirmed": True,
        "version_status": "effective",
        "index_status": "ready",
        "effective_year": 2020,
        "invalid_year": None,
    }


class SemanticComplianceTests(unittest.TestCase):
    def test_normalize_common_provider_status_aliases(self):
        cases = {
            "non_compliant": "issue_found",
            "compliant": "no_issue",
            "needs_manual_review": "manual_review",
        }
        for provider_status, expected in cases.items():
            with self.subTest(provider_status=provider_status):
                self.assertEqual(
                    normalize_compliance_conclusion({"result_status": provider_status})["result_status"],
                    expected,
                )
    def test_incomplete_coverage_cannot_supply_normative_evidence(self):
        result = select_published_clause_evidence({"coverage": [{"coverage_status": "uncovered"}], "evidence": [{"clause_id": "1", "text": "x"}]}, None)
        self.assertEqual(result, ())

    def test_noncompliance_requires_document_and_normative_evidence(self):
        evidence = ({"clause_id": "c1", "text": "完整条款", "release_id": "r1", "version_id": "v1", "source_type": "spec"},)
        with self.assertRaises(ValueError):
            validate_compliance_conclusion({"result_status": "issue_found", "document_evidence_ids": ["d1"]}, {"d1"}, evidence)

    def test_clause_evidence_is_complete_and_traceable(self):
        result = select_published_clause_evidence({"coverage": [{"coverage_status": "covered"}], "evidence": [{"clause_id": "c1", "text": "完整条款", "release_id": "r1", "version_id": "v1", "source_type": "spec", **eligible_version_fields()}]}, None)
        self.assertEqual(result[0]["evidence_type"], "normative_clause")
        self.assertEqual(validate_compliance_conclusion({"result_status": "issue_found", "document_evidence_ids": ["d1"], "normative_evidence_ids": ["c1"]}, {"d1"}, result)["result_status"], "issue_found")

    def test_declared_normative_text_filters_unlisted_candidate(self):
        scope = SimpleNamespace(
            declared_families=("《页岩气地面工程设计规范》 Q/SY 1858-2015",),
            family_ids=("family-1",),
        )
        result = select_published_clause_evidence(
            {
                "coverage": [{"coverage_status": "covered"}],
                "evidence": [
                    {
                        "clause_id": "c1", "text": "条款一", "release_id": "r1",
                        "version_id": "v1", "family_id": "family-1",
                        "standard_code": "Q/SY1858-2015",
                        "source_type": "spec", **eligible_version_fields(),
                    },
                    {
                        "clause_id": "c2", "text": "条款二", "release_id": "r1",
                        "version_id": "v2", "family_id": "family-2",
                        "standard_code": "GB50052-2009", "source_type": "spec", **eligible_version_fields(),
                    },
                ],
            },
            scope,
        )
        self.assertEqual([item["clause_id"] for item in result], ["c1"])

    def test_only_canonicalized_declared_families_can_supply_automatic_evidence(self):
        scope = NormativeScope.freeze(
            2025,
            ["《页岩气地面工程设计规范》 Q/SY 1858-2015"],
            ["supplemental-family"],
        )

        selected, trace, warnings = filter_clause_candidates(
            {"evidence": [
                {
                    "clause_id": "declared", "version_id": "declared-version", "release_id": "r1",
                    "standard_code": "Q/SY1858-2015", "text": "声明规范条款", "source_type": "spec",
                    **eligible_version_fields(),
                },
                {
                    "clause_id": "supplemental", "version_id": "supplemental-version", "release_id": "r1",
                    "family_id": "supplemental-family", "text": "补充规范条款", "source_type": "spec",
                    **eligible_version_fields(),
                },
            ]},
            scope,
        )

        self.assertEqual([item["clause_id"] for item in selected], ["declared"])
        self.assertEqual(trace[1]["filter_reason"], "not_declared_norm")
        self.assertEqual(warnings, ("declared_norm_omission",))

    def test_opaque_candidate_without_normative_identity_is_never_automatic_evidence(self):
        scope = NormativeScope.freeze(2025, ["Q/SY 1858-2015"], ["supplemental-family"])

        selected, trace, warnings = filter_clause_candidates(
            {"evidence": [{
                "clause_id": "opaque", "version_id": "20d13f65-24b4-42bd-929f-9514d45d9808",
                "release_id": "enabled-corpus", "text": "补充规范条款", "source_type": "spec",
                **eligible_version_fields(),
            }]},
            scope,
        )

        self.assertEqual(selected, ())
        self.assertEqual(trace[0]["filter_reason"], "not_declared_norm")
        self.assertEqual(warnings, ("declared_norm_omission",))

    def test_production_shaped_identity_selects_declared_and_omits_undeclared_candidate(self):
        scope = NormativeScope.freeze(2025, ["《页岩气地面工程设计规范》 Q/SY 1858-2015"], [])
        common = {
            "release_id": "enabled-corpus", "source_type": "spec", "text": "完整条款",
            **eligible_version_fields(),
        }

        selected, trace, warnings = filter_clause_candidates(
            {"evidence": [
                {
                    **common, "clause_id": "declared", "version_id": "version-1", "family_id": "family-1",
                    "standard_code": "Q/SY1858-2015", "standard_code_base": "Q/SY1858",
                    "canonical_name": "页岩气地面工程设计规范", "display_name": "页岩气地面工程设计规范 2015",
                },
                {
                    **common, "clause_id": "undeclared", "version_id": "version-2", "family_id": "family-2",
                    "standard_code": "GB 50052-2009", "standard_code_base": "GB50052",
                    "canonical_name": "供配电系统设计规范", "display_name": "供配电系统设计规范 2009",
                },
            ]},
            scope,
        )

        self.assertEqual([item["clause_id"] for item in selected], ["declared"])
        self.assertEqual(trace[1]["filter_reason"], "not_declared_norm")
        self.assertEqual(warnings, ("declared_norm_omission",))


if __name__ == "__main__":
    unittest.main()
