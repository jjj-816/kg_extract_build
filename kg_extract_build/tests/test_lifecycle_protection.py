import unittest
from unittest.mock import MagicMock, patch

from kg_extract_build import dashboard


class LifecycleProtectionTests(unittest.TestCase):
    def test_delete_blocked_when_normative_referenced(self):
        config = {"host": "h", "port": 1, "user": "u", "password": "p", "database": "d", "charset": "utf8mb4"}

        class FakeStore:
            def get_deletion_state(self, run_id):
                return "active"

            def run_document_ids(self, run_id):
                return [36]

        class FakeNormStore:
            def has_normative_references(self, document_id):
                return document_id == 36

        with patch.object(dashboard, "MySQLExperimentStore", return_value=FakeStore()), \
             patch.object(dashboard, "NormativeStore", return_value=FakeNormStore()):
            result = dashboard.delete_run_with_vectors(config, "run-1")
        self.assertFalse(result.deleted)
        self.assertEqual(result.state, "normative_referenced")
        self.assertIn("只允许归档", result.message)

    def test_delete_proceeds_when_no_references(self):
        config = {"host": "h", "port": 1, "user": "u", "password": "p", "database": "d", "charset": "utf8mb4"}

        class FakeStore:
            def get_deletion_state(self, run_id):
                return "active"

            def run_document_ids(self, run_id):
                return [36]

            def mark_vectors_deleted_sql_pending(self, run_id):
                return True

            def delete_run(self, run_id):
                return True

        class FakeNormStore:
            def has_normative_references(self, document_id):
                return False

        mock_vs = MagicMock()
        with patch.object(dashboard, "MySQLExperimentStore", return_value=FakeStore()), \
             patch.object(dashboard, "NormativeStore", return_value=FakeNormStore()), \
             patch.object(dashboard, "build_vector_store", return_value=mock_vs):
            result = dashboard.delete_run_with_vectors(config, "run-1")
        self.assertTrue(result.deleted)
        mock_vs.delete_segments_by_run.assert_called_once_with("run-1")
        mock_vs.close.assert_called_once()
