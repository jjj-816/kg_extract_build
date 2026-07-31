import unittest

from kg_extract_build.audit.persistence import validate_audit_context


class AuditContextValidationTests(unittest.TestCase):
    def test_rejects_incomplete_context(self):
        with self.assertRaisesRegex(ValueError, "项目或平台名称"):
            validate_audit_context({"audit_year": 2025, "work_purpose": "", "work_types": []}, "")

    def test_accepts_complete_context(self):
        validate_audit_context(
            {"project_name": "长宁H25A", "audit_year": 2025, "work_purpose": "地面集输施工", "work_types": ["动土作业"]},
            "审核员",
        )
