import unittest
from datetime import datetime

from kg_extract_build.audit.persistence import format_beijing_time, format_utc_time, validate_audit_context


class AuditContextValidationTests(unittest.TestCase):
    def test_rejects_incomplete_context(self):
        with self.assertRaisesRegex(ValueError, "项目或平台名称"):
            validate_audit_context({"audit_year": 2025, "work_purpose": "", "work_types": []}, "")

    def test_accepts_complete_context(self):
        validate_audit_context(
            {"project_name": "长宁H25A", "audit_year": 2025, "work_purpose": "地面集输施工", "work_types": ["动土作业"]},
            "审核员",
        )

    def test_utc_database_time_is_labeled_and_converted_to_beijing(self):
        value = datetime(2026, 7, 31, 16, 30, 0)
        self.assertEqual(format_utc_time(value), "2026-07-31T16:30:00Z")
        self.assertIn("2026-08-01 00:30:00", format_beijing_time(value))
