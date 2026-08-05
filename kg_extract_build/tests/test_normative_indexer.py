import unittest
from types import SimpleNamespace
from unittest import mock

from kg_extract_build.normative_indexer import NormativeIndexer

from test_normative_persistence import InMemoryBackend


class FakeNormativeVectorStore:
    def __init__(self):
        self.records = []

    def ensure_collection(self, profile):
        return None

    def collection_name(self, profile):
        return f"kg_normative_clauses__minilm_384__v1"

    def upsert_segments(self, profile, records):
        self.records.extend(records)

    def search(self, profile, query_vector, index_ids, version_ids, limit=30):
        return []

    def close(self):
        pass


class FakeEncoder:
    def __init__(self):
        self.encoded = []

    def encode_documents(self, texts):
        self.encoded.extend(texts)
        return [[0.1] * 384 for _ in texts]

    def encode_query(self, text):
        return [0.1] * 384

    def tokenize(self, text):
        return text.split(" ")

    def close(self):
        pass


def make_store(version_rows, clause_rows):
    backend = InMemoryBackend()
    for row in version_rows:
        backend.rows["kg_normative_version"].append(row)
    backend.rows["kg_normative_clause"] = clause_rows
    clause_set_id = clause_rows[0]["clause_set_id"] if clause_rows else "set-1"
    return SimpleNamespace(
        _backend=backend,
        get_version=lambda vid: next((r for r in version_rows if r["version_id"] == vid), None),
        latest_clause_set=lambda vid: {"clause_set_id": clause_set_id},
        get_clauses=lambda cid: [r for r in clause_rows if r.get("clause_set_id") == cid],
        save_index=lambda record: backend.rows.setdefault("kg_normative_index", []).append(record),
        save_segments=lambda index_id, segs: backend.rows.setdefault("segments", []).extend(segs),
        get_index_by_fingerprint=lambda fp: next((r for r in backend.rows.get("kg_normative_index", []) if r["index_fingerprint"] == fp), None),
    )


def _make_profile():
    return SimpleNamespace(
        embedding_model_key="minilm", embedding_model_revision="r",
        embedding_dimension=384, max_input_tokens=128,
        document_prefix="", query_prefix="", normalize=True,
        pooling="mean",
    )


class IndexerTests(unittest.TestCase):
    def test_build_index_ready_and_persists(self):
        store = make_store(
            [{"version_id": "v1", "family_id": "f1", "document_id": 36,
              "effective_year": 2020, "invalid_year": None,
              "metadata_confirmed": True, "status": "effective",
              "metadata_hash": "mh-1"}],
            [{"clause_set_id": "set-1", "clause_number": "第二十条",
              "raw_text": "作业前应通风。", "normalized_text": "作业前应通风。",
              "start_offset": 0, "end_offset": 8, "content_hash": "h",
              "parse_status": "structured", "hierarchy_path": ["总则"],
              "clause_id": 501}],
        )
        encoder = FakeEncoder()
        indexer = NormativeIndexer(
            store, FakeNormativeVectorStore(), encoder, _make_profile(),
        )
        result = indexer.build_index("v1")
        self.assertEqual(result["status"], "ready")
        self.assertTrue(encoder.encoded)

    def test_build_index_skips_when_fingerprint_exists(self):
        store = make_store(
            [{"version_id": "v1", "family_id": "f1", "document_id": 36,
              "effective_year": 2020, "invalid_year": None,
              "metadata_confirmed": True, "status": "effective",
              "metadata_hash": "mh-1"}],
            [{"clause_set_id": "set-1", "clause_number": "第二十条",
              "raw_text": "作业前应通风。", "normalized_text": "作业前应通风。",
              "start_offset": 0, "end_offset": 8, "content_hash": "h",
              "parse_status": "structured", "hierarchy_path": ["总则"],
              "clause_id": 501}],
        )
        store._backend.rows["kg_normative_index"] = [{"index_fingerprint": "fp", "index_id": "idx-0"}]
        indexer = NormativeIndexer(store, FakeNormativeVectorStore(), FakeEncoder(), _make_profile())
        with mock.patch("kg_extract_build.normative_indexer.build_index_fingerprint", return_value="fp"):
            result = indexer.build_index("v1")
        self.assertEqual(result["status"], "skipped")

    def test_build_index_failed_when_no_clauses(self):
        store = make_store(
            [{"version_id": "v1", "family_id": "f1", "document_id": 36,
              "effective_year": 2020, "invalid_year": None,
              "metadata_confirmed": True, "status": "effective",
              "metadata_hash": "mh-1"}],
            [],
        )
        indexer = NormativeIndexer(store, FakeNormativeVectorStore(), FakeEncoder(), _make_profile())
        result = indexer.build_index("v1")
        self.assertEqual(result["status"], "failed")
        self.assertIn("条款", result["reason"])
