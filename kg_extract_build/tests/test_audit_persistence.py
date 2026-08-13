import unittest
from datetime import datetime
from types import SimpleNamespace

from kg_extract_build.audit.persistence import MySQLAuditStore, format_beijing_time, format_utc_time, validate_audit_context


class RecordingCursor:
    def __init__(self):
        self.statements = []
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.statements.append((" ".join(sql.split()), params))
        if "SELECT execution_id,task_id FROM audit_task_execution" in sql:
            self._rows = [(41, "SEM-1")]
        else:
            self._rows = []

    def fetchall(self):
        return list(self._rows)


class RecordingConnection:
    def __init__(self):
        self.cursor_instance = RecordingCursor()
        self.commits = 0
        self.rollbacks = 0

    def ping(self, reconnect=True):
        return None

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


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

    def test_execution_results_persist_each_evidence_kind_without_rolling_back(self):
        connection = RecordingConnection()
        store = MySQLAuditStore()
        store._connection_instance = connection
        result = SimpleNamespace(
            task_id="SEM-1", route="semantic_compliance", execution_status="completed", result_status="no_issue",
            evidence=(
                {"evidence_type": "document", "block_id": "block-1", "raw_text": "方案原文"},
                {"evidence_type": "normative_clause", "clause_id": "501", "version_id": "version-1", "text": "规范条款"},
                {"evidence_type": "graph_clue", "clue_id": "clue-9", "assertion_id": "assertion-2", "evidence_sentence": "历史案例"},
            ), issues=(), manual_reviews=(), offline_items=(), advisories=(), diagnostics=(),
        )

        store.save_execution_results("run-1", (result,))

        evidence_params = [
            params for sql, params in connection.cursor_instance.statements
            if sql.startswith("INSERT INTO audit_task_evidence")
        ]
        self.assertEqual(
            [(params[1], params[2], params[3]) for params in evidence_params],
            [
                ("document", None, "block-1"),
                ("normative_clause", "501", None),
                ("graph_clue", "clue-9", None),
            ],
        )
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
