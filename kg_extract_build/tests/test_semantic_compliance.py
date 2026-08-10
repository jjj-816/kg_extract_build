import unittest

from kg_extract_build.audit.semantic_compliance import (
    select_published_clause_evidence,
    validate_compliance_conclusion,
)


class SemanticComplianceTests(unittest.TestCase):
    def test_incomplete_coverage_cannot_supply_normative_evidence(self):
        result = select_published_clause_evidence({"coverage": [{"coverage_status": "uncovered"}], "evidence": [{"clause_id": "1", "text": "x"}]}, None)
        self.assertEqual(result, ())

    def test_noncompliance_requires_document_and_normative_evidence(self):
        evidence = ({"clause_id": "c1", "text": "完整条款", "release_id": "r1", "version_id": "v1", "source_type": "spec"},)
        with self.assertRaises(ValueError):
            validate_compliance_conclusion({"result_status": "issue_found", "document_evidence_ids": ["d1"]}, {"d1"}, evidence)

    def test_clause_evidence_is_complete_and_traceable(self):
        result = select_published_clause_evidence({"coverage": [{"coverage_status": "covered"}], "evidence": [{"clause_id": "c1", "text": "完整条款", "release_id": "r1", "version_id": "v1", "source_type": "spec"}]}, None)
        self.assertEqual(result[0]["evidence_type"], "normative_clause")
        self.assertEqual(validate_compliance_conclusion({"result_status": "issue_found", "document_evidence_ids": ["d1"], "normative_evidence_ids": ["c1"]}, {"d1"}, result)["result_status"], "issue_found")


if __name__ == "__main__":
    unittest.main()
