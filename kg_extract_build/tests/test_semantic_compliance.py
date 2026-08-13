import unittest
from types import SimpleNamespace

from kg_extract_build.audit.semantic_compliance import (
    select_published_clause_evidence,
    validate_compliance_conclusion,
)


def eligible_version_fields():
    return {
        "metadata_confirmed": True,
        "version_status": "effective",
        "index_status": "ready",
        "effective_year": 2020,
        "invalid_year": None,
    }


class SemanticComplianceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
