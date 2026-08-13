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
        with patch.object(dn.st, "selectbox", side_effect=["有限空间作业安全规范 2020（version-confined-space）", mismatched]), \
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

    def test_mismatched_asset_keeps_confirmed_management_controls(self):
        mismatched = {
            "family_id": "family-shale-gas", "canonical_name": "页岩气地面工程设计规范",
            "standard_code_base": "Q/SY1858", "version_id": "version-confined-space",
            "display_name": "有限空间作业安全规范 2020", "standard_code": "GB 30871-2022",
            "family_consistency": "mismatch", "index_id": "index-1", "version_year": 2020,
            "effective_year": 2020, "version_status": "effective", "metadata_confirmed": True,
            "index_status": "ready", "audit_disabled_at": None, "clause_count": 5,
            "collection_name": "normative", "release_count": 0,
        }
        store = MagicMock()
        store.list_versions.return_value = [mismatched]
        store.asset_overview.return_value = [mismatched]
        label = "有限空间作业安全规范 2020（version-confined-space）"
        with patch.object(dn.st, "selectbox", side_effect=[label, mismatched]), \
             patch.object(dn.st, "caption"), patch.object(dn.st, "dataframe"), \
             patch.object(dn.st, "warning"), patch.object(dn.st, "button", return_value=False), \
             patch.object(dn.st, "checkbox", return_value=False) as checkbox:
            dn.render_index_area(store, MagicMock(), MagicMock())

        labels = [call.args[0] for call in checkbox.call_args_list]
        self.assertTrue(any("确认停用误挂资产" in label for label in labels))
        self.assertTrue(any("彻底删除该规范版本" in label for label in labels))

    def test_management_selector_targets_mismatch_when_normal_index_also_exists(self):
        normal = {
            "family_id": "family-shale-gas", "canonical_name": "页岩气地面工程设计规范",
            "standard_code_base": "Q/SY1858", "version_id": "version-shale-gas",
            "display_name": "页岩气地面工程设计规范 2015", "standard_code": "Q/SY1858-2015",
            "family_consistency": "match", "index_id": "index-normal", "version_year": 2015,
            "effective_year": 2015, "version_status": "effective", "metadata_confirmed": True,
            "index_status": "ready", "audit_disabled_at": None, "clause_count": 5,
            "collection_name": "normative", "release_count": 0,
        }
        mismatched = {
            **normal, "version_id": "version-confined-space", "display_name": "有限空间作业安全规范 2020",
            "standard_code": "GB 30871-2022", "family_consistency": "mismatch", "index_id": "index-mismatch",
        }
        store = MagicMock()
        store.list_versions.return_value = [normal]
        store.asset_overview.return_value = [normal, mismatched]
        normal_label = "页岩气地面工程设计规范 2015（version-shale-gas）"
        with patch.object(dn.st, "selectbox", side_effect=[normal_label, normal, mismatched]), \
             patch.object(dn.st, "caption"), patch.object(dn.st, "dataframe"), \
             patch.object(dn.st, "warning"), patch.object(dn.st, "checkbox", return_value=True), \
             patch.object(dn.st, "button", side_effect=[False, True, False, False, False, False]), patch.object(dn.st, "rerun"):
            dn.render_index_area(store, MagicMock(), MagicMock())

        store.set_audit_enabled.assert_called_once_with("index-mismatch", False)
