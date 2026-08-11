import unittest

from kg_extract_build.audit.normative_production import PublishedNormativeAdapter
from kg_extract_build.audit.normative_scope import NormativeScope
from kg_extract_build.normative import NormativeVersionCandidate


class Store:
    def release_member_index_ids(self, release_id):
        return ["i1"]
    def index_rows(self, ids):
        return [{"index_id": "i1", "version_id": "v1", "status": "ready"}]
    def version_candidates(self):
        return [NormativeVersionCandidate("v1", "f1", 2025, None, True, "published")]


class Searcher:
    def search(self, request):
        return {"coverage": [], "evidence": [{"release_id": request.release_id, "version_id": "v1", "clause_id": "c1", "text": "完整条款"}]}


class NormativeProductionTests(unittest.TestCase):
    def test_published_clause_is_retained(self):
        adapter = PublishedNormativeAdapter(Store(), Searcher())
        result = adapter.search(query="安全", audit_year=2025, release_id="rel-1", scope=NormativeScope.freeze(2025, ["f1"], []))
        self.assertEqual(result["evidence"][0]["clause_id"], "c1")

    def test_uncovered_scope_blocks_conclusion(self):
        adapter = PublishedNormativeAdapter(Store(), Searcher())
        result = adapter.search(query="安全", audit_year=2025, release_id="rel-1", scope=NormativeScope.freeze(2025, ["missing"], []))
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["diagnostic"]["status"], "coverage_blocked")


if __name__ == "__main__":
    unittest.main()
