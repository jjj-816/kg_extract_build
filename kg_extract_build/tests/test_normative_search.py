import unittest

from kg_extract_build.normative import NormativeVersionCandidate
from kg_extract_build.normative_search import NormativeSearcher, SearchRequest


class FakeStore:
    def __init__(self, versions, clauses, index_map, release_members, indexes):
        self._versions = versions
        self._clauses = clauses
        self._index_map = index_map
        self._release_members = release_members
        self._indexes = indexes

    def version_candidates(self):
        return self._versions

    def release_member_index_ids(self, release_id):
        return self._release_members

    def index_rows(self, index_ids):
        return [r for r in self._indexes if r["index_id"] in index_ids]

    def get_clauses(self, clause_set_id):
        return [c for c in self._clauses if c["clause_set_id"] == clause_set_id]


class FakeVectorStore:
    def __init__(self, hits):
        self._hits = hits

    def search(self, profile, query_vector, index_ids, version_ids, limit=30):
        return self._hits[:limit]

    def close(self):
        pass


class FakeEncoder:
    def encode_query(self, text):
        return [0.1] * 4


PROFILE = {"embedding_model_key": "minilm", "embedding_dimension": 384}


class SearchTests(unittest.TestCase):
    def test_aggregates_segments_and_returns_full_clause(self):
        versions = [NormativeVersionCandidate("v1", "f1", 2020, None, True, "effective")]
        clauses = [{"clause_set_id": "set-1", "clause_id": 501, "clause_number": "第二十条",
                    "raw_text": "有限空间作业应当先通风。", "content_hash": "h1"}]
        hits = [
            {"index_id": "i1", "clause_id": 501, "version_id": "v1", "family_id": "f1",
             "clause_set_id": "set-1", "clause_number": "第二十条", "text_hash": "s1", "score": 0.9},
            {"index_id": "i1", "clause_id": 501, "version_id": "v1", "family_id": "f1",
             "clause_set_id": "set-1", "clause_number": "第二十条", "text_hash": "s2", "score": 0.7},
        ]
        store = FakeStore(versions, clauses, {"v1": "i1"}, ["i1"],
                          [{"index_id": "i1", "clause_set_id": "set-1", "version_id": "v1", "family_id": "f1"}])
        searcher = NormativeSearcher(store, FakeVectorStore(hits), FakeEncoder(), PROFILE)
        result = searcher.search(SearchRequest("通风", 2025, "rel-1", {}, top_k=1))
        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual(result["evidence"][0]["clause_id"], 501)
        self.assertEqual(result["evidence"][0]["text"], "有限空间作业应当先通风。")
        self.assertEqual(result["retrieval_trace"]["unique_clause_count"], 1)

    def test_expands_window_when_dedup_below_topk(self):
        versions = [NormativeVersionCandidate("v1", "f1", 2020, None, True, "effective")]
        clauses = [{"clause_set_id": "set-1", "clause_id": 501, "clause_number": "第二十条",
                    "raw_text": "A 条款。", "content_hash": "h1"}]
        index_rows = [{"index_id": "i1", "clause_set_id": "set-1", "version_id": "v1", "family_id": "f1"}]

        base_hit = {"index_id": "i1", "clause_id": 501, "version_id": "v1", "family_id": "f1",
                     "clause_set_id": "set-1", "clause_number": "第二十条", "text_hash": "s", "score": 0.5}

        class ExpandingVectorStore(FakeVectorStore):
            def __init__(self):
                super().__init__([])
                self.calls = []

            def search(self, profile, query_vector, index_ids, version_ids, limit=30):
                self.calls.append(limit)
                if limit >= 60:
                    return [{"index_id": "i1", "clause_id": 501, "version_id": "v1", "family_id": "f1",
                             "clause_set_id": "set-1", "clause_number": "第二十条", "text_hash": "s", "score": 0.5},
                            {"index_id": "i1", "clause_id": 502, "version_id": "v1", "family_id": "f1",
                             "clause_set_id": "set-1", "clause_number": "第二十一条", "text_hash": "t", "score": 0.4}]
                # P6 fix: return `limit` hits all with same clause_id 501,
                # so len(hits)==raw_limit and the loop doesn't break early.
                return [base_hit for _ in range(limit)]

        store = FakeStore(versions, clauses, {"v1": "i1"}, ["i1"], index_rows)
        vector_store = ExpandingVectorStore()
        searcher = NormativeSearcher(store, vector_store, FakeEncoder(), PROFILE)
        result = searcher.search(SearchRequest("查询", 2025, "rel-1", {}, top_k=2))
        self.assertEqual(len(result["evidence"]), 2)
        self.assertGreater(len(vector_store.calls), 1)
