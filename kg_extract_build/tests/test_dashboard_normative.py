import unittest
from unittest.mock import patch

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
        with patch.object(dn.st, "subheader"), \
             patch.object(dn.st, "form_submit_button", return_value=True), \
             patch.object(dn.st, "text_input", return_value="通风"), \
             patch.object(dn.st, "number_input", return_value=2025), \
             patch.object(dn.st, "selectbox", return_value="rel-1"), \
             patch.object(dn.st, "slider", return_value=5), \
             patch.object(dn.st, "dataframe"), patch.object(dn.st, "write"):
            dn.render_search_preview(FakeSearcher().__class__, searcher, {"rel-1": "rel-1"})
        self.assertTrue(searcher.searched)
