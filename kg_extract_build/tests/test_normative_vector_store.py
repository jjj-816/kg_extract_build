import unittest

from kg_extract_build.normative_encoder import EncoderProfile
from kg_extract_build.normative_vector_store import NormativeMilvusStore

MINILM = EncoderProfile("paraphrase-multilingual-MiniLM-L12-v2", "rev", 384)


class FakeMilvusClient:
    def __init__(self, **kwargs):
        self.collections = set()
        self.dimensions = {}
        self.upserted = []
        self.searched = None

    def has_collection(self, collection_name):
        return collection_name in self.collections

    def create_collection(self, collection_name, dimension, **kwargs):
        if collection_name in self.collections:
            raise ValueError(f"exists {collection_name}")
        self.collections.add(collection_name)
        self.dimensions[collection_name] = dimension

    def describe_collection(self, collection_name):
        return {"params": {"dimension": self.dimensions[collection_name]}}

    def upsert(self, collection_name, data):
        self.upserted.extend(data)

    def search(self, collection_name, data, filter="", limit=10, output_fields=None, anns_field="embedding"):
        self.searched = dict(collection_name=collection_name, data=data, filter=filter, limit=limit)
        return [[{"entity": {"clause_id": 1, "version_id": "v1", "index_id": "i1"},
                  "distance": 0.9} for _ in range(limit)]]

    def close(self):
        pass


class NormativeVectorStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = NormativeMilvusStore("http://x", collection_prefix="kg_normative_clauses")
        self.store.client = FakeMilvusClient()

    def test_collection_name_uses_model_and_dimension(self):
        self.assertEqual(
            self.store.collection_name(MINILM),
            "kg_normative_clauses__minilm_384__v1",
        )

    def test_dimension_mismatch_rejected(self):
        self.store.ensure_collection(MINILM)
        other = EncoderProfile("paraphrase-multilingual-MiniLM-L12-v2", "rev", 512)
        # 集合名内编码维度，故同名集合若已被错误创建为不符维度
        # （旧版本/手工误建残留），ensure_collection 必须拒绝而非复用。
        wrong = self.store.collection_name(other)
        self.store.client.collections.add(wrong)
        self.store.client.dimensions[wrong] = 384
        with self.assertRaises(ValueError):
            self.store.ensure_collection(other)

    def test_upsert_and_search_pass_stable_ids(self):
        profile = MINILM
        self.store.ensure_collection(profile)
        self.store.upsert_segments(profile, [{
            "segment_id": 1, "index_id": "idx-1", "clause_id": 501,
            "clause_set_id": "set-1", "version_id": "v1", "family_id": "f1",
            "document_id": 36, "source_type": "spec", "clause_number": "第二十条",
            "text_hash": "h", "embedding": [0.1] * 384,
        }])
        hits = self.store.search(profile, [0.1] * 384, ["idx-1"], ["v1"], limit=10)
        self.assertEqual(hits[0]["clause_id"], 1)
        self.assertIn("idx-1", self.store.client.searched["filter"])
