import unittest
from unittest.mock import MagicMock, patch

import kg_extract_build.dashboard_normative as dn


class DashboardNormativeTests(unittest.TestCase):
    def test_render_calls_search_when_form_submitted(self):
        class FakeSearcher:
            def __init__(self, *a, **k):
                self.searched = False

            def search(self, request):
                self.searched = True
                return {"coverage": [], "evidence": [], "retrieval_trace": {}, "warnings": []}

        searcher = FakeSearcher()
        with patch.object(dn.st, "form_submit_button", return_value=True), \
             patch.object(dn.st, "text_input", return_value="通风"), \
             patch.object(dn.st, "number_input", return_value=2025), \
             patch.object(dn.st, "selectbox", return_value="rel-1"), \
             patch.object(dn.st, "slider", return_value=5), \
             patch.object(dn.st, "subheader"), \
             patch.object(dn.st, "form", return_value=MagicMock()), \
             patch.object(dn.st, "dataframe"), patch.object(dn.st, "write"):
            dn.render_search_preview(FakeSearcher().__class__, searcher, {"rel-1": "rel-1"})
        self.assertTrue(searcher.searched)

    def test_index_area_warns_and_does_not_offer_mismatched_asset_for_enablement(self):
        mismatched = {
            "family_id": "family-shale-gas",
            "canonical_name": "页岩气地面工程设计规范",
            "standard_code_base": "Q/SY1858",
            "version_id": "version-confined-space",
            "display_name": "有限空间作业安全规范 2020",
            "standard_code": "GB 30871-2022",
            "family_consistency": "mismatch",
            "eligible_for_supersession": False,
            "index_id": "index-1",
            "version_year": 2020,
            "effective_year": 2020,
            "version_status": "effective",
            "metadata_confirmed": True,
            "index_status": "ready",
            "audit_disabled_at": None,
            "clause_count": 5,
            "collection_name": "normative",
            "release_count": 0,
        }

        store = MagicMock()
        store.list_versions.return_value = [mismatched]
        store.asset_overview.return_value = [mismatched]
        with patch.object(dn.st, "selectbox", return_value="有限空间作业安全规范 2020（version-confined-space）"), \
             patch.object(dn.st, "caption"), patch.object(dn.st, "dataframe"), \
             patch.object(dn.st, "warning") as warning, patch.object(dn.st, "button", return_value=False):
            dn.render_index_area(store, MagicMock(), MagicMock())

        self.assertTrue(any("规范族不一致" in str(call) for call in warning.call_args_list))

    def test_confirmed_version_deletion_cleans_every_attached_vector_index(self):
        store = MagicMock()
        store.historical_version_references.return_value = []
        store.index_rows_for_version.return_value = [{"index_id": "index-1"}, {"index_id": "index-2"}]
        vector_store = MagicMock()

        dn.delete_normative_version(store, vector_store, MagicMock(), "version-confined-space")

        self.assertEqual(
            [call.args[1] for call in vector_store.delete_index.call_args_list],
            ["index-1", "index-2"],
        )
        store.delete_version_records.assert_called_once_with("version-confined-space")
