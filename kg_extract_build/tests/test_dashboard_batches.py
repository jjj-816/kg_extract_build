import unittest
from unittest.mock import Mock, patch

from kg_extract_build import dashboard


class _Expander:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _DashboardUI:
    def __init__(self, confirmed=False, clicked=False):
        self.confirmed = confirmed
        self.clicked = clicked
        self.session_state = {}
        self.delete_disabled = None
        self.messages = []

    def expander(self, *_args, **_kwargs):
        return _Expander()

    def caption(self, *_args, **_kwargs):
        return None

    def checkbox(self, *_args, **_kwargs):
        return self.confirmed

    def button(self, *_args, **kwargs):
        self.delete_disabled = kwargs["disabled"]
        return self.clicked

    def success(self, message):
        self.messages.append(("success", message))

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))

    def rerun(self):
        self.messages.append(("rerun", None))


class DashboardBatchDeletionTests(unittest.TestCase):
    selected_completed = {
        "run_id": "run-123",
        "run_name": "completed batch",
        "status": "completed",
        "document_count": 3,
        "final_triplet_count": 9,
    }

    def render_runs_page(self, selected, confirmed=False, clicked=False):
        page = _DashboardUI(confirmed=confirmed, clicked=clicked)
        with patch.object(dashboard, "st", page):
            dashboard.render_delete_panel({}, selected)
        return page

    def test_delete_action_is_not_called_without_confirmation(self):
        service = Mock()
        with patch.object(dashboard, "delete_run_with_vectors", service):
            self.render_runs_page(self.selected_completed, confirmed=False, clicked=False)
        service.assert_not_called()

    def test_confirmed_completed_run_deletes_vectors_then_sql(self):
        events = []
        test_case = self

        class VectorStore:
            def delete_segments_by_run(self, run_id):
                test_case.assertEqual(run_id, "run-123")
                events.append("vectors")

            def close(self):
                events.append("close")

        class Store:
            def get_deletion_state(self, run_id):
                test_case.assertEqual(run_id, "run-123")
                return "active"

            def mark_vectors_deleted_sql_pending(self, run_id):
                test_case.assertEqual(run_id, "run-123")
                events.append("pending")
                return True

            def delete_run(self, run_id):
                test_case.assertEqual(run_id, "run-123")
                events.append("sql")
                return True

        with patch.object(dashboard, "build_vector_store", return_value=VectorStore()), patch.object(
            dashboard, "MySQLExperimentStore", return_value=Store()
        ):
            deleted = dashboard.delete_run_with_vectors({}, "run-123")

        self.assertTrue(deleted.deleted)
        self.assertEqual(events, ["vectors", "close", "pending", "sql"])

    def test_running_run_has_no_enabled_delete_button(self):
        selected = dict(self.selected_completed, status="running")
        page = self.render_runs_page(selected, confirmed=True, clicked=False)
        self.assertTrue(page.delete_disabled)

    def test_vector_delete_failure_closes_store_without_deleting_sql(self):
        events = []

        class VectorStore:
            def delete_segments_by_run(self, _run_id):
                events.append("vectors")
                raise RuntimeError("Milvus unavailable")

            def close(self):
                events.append("close")

        sql_store = Mock()
        sql_store.get_deletion_state.return_value = "active"
        with patch.object(dashboard, "build_vector_store", return_value=VectorStore()), patch.object(
            dashboard, "MySQLExperimentStore", return_value=sql_store
        ):
            with self.assertRaisesRegex(RuntimeError, "Milvus unavailable"):
                dashboard.delete_run_with_vectors({}, "run-123")

        self.assertEqual(events, ["vectors", "close"])
        sql_store.delete_run.assert_not_called()

    def test_sql_failure_after_vector_delete_is_resumable(self):
        store = Mock()
        store.get_deletion_state.return_value = "active"
        store.mark_vectors_deleted_sql_pending.return_value = True
        store.delete_run.return_value = False
        vector_store = Mock()
        with patch.object(dashboard, "build_vector_store", return_value=vector_store), patch.object(
            dashboard, "MySQLExperimentStore", return_value=store
        ):
            result = dashboard.delete_run_with_vectors({}, "run-123")
        self.assertEqual(result.state, "vectors_deleted_sql_pending")
        store.mark_vectors_deleted_sql_pending.assert_called_once_with("run-123")

    def test_resume_deletion_does_not_call_vector_store(self):
        store = Mock()
        store.get_deletion_state.return_value = "vectors_deleted_sql_pending"
        store.delete_run.return_value = True
        with patch.object(dashboard, "build_vector_store") as vectors, patch.object(
            dashboard, "MySQLExperimentStore", return_value=store
        ):
            result = dashboard.resume_pending_run_deletion({}, "run-123")
        self.assertTrue(result.deleted)
        vectors.assert_not_called()


if __name__ == "__main__":
    unittest.main()
