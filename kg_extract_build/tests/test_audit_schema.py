import unittest

from kg_extract_build.audit.persistence import audit_schema_path


class AuditSchemaTests(unittest.TestCase):
    def test_schema_contains_the_stage_one_audit_data_domain(self):
        schema = audit_schema_path().read_text(encoding="utf-8")
        for table in (
            "audit_document",
            "audit_document_block",
            "audit_run",
            "audit_run_work_type",
            "audit_task_execution",
            "audit_declared_norm",
            "audit_task_evidence",
            "audit_retrieval_candidate",
            "audit_applicability_result",
            "audit_llm_call",
            "audit_issue",
            "audit_human_review",
            "audit_report",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
        self.assertIn("uk_audit_execution_run_task", schema)


if __name__ == "__main__":
    unittest.main()
