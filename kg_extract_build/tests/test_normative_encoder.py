import sys
import types
import unittest

import numpy as np


class FakeSentenceTransformer:
    def __init__(self, model_path):
        self._model_path = str(model_path)

    def encode(self, texts, convert_to_numpy=True):
        return np.random.RandomState(0).rand(len(texts), 4)

    def tokenize(self, text):
        return text.split(" ")


sys.modules["sentence_transformers"] = types.SimpleNamespace(
    SentenceTransformer=FakeSentenceTransformer
)

from kg_extract_build.normative_encoder import (
    EncoderProfile,
    NormativeEncoder,
    build_encoder_profile_hash,
    model_revision,
)


class EncoderTests(unittest.TestCase):
    def test_profile_hash_stable_and_sensitive(self):
        p = EncoderProfile("model-a", "rev-1", 384, "查询：", "条款：")
        self.assertEqual(build_encoder_profile_hash(p), build_encoder_profile_hash(p))
        q = EncoderProfile("model-a", "rev-2", 384, "查询：", "条款：")
        self.assertNotEqual(build_encoder_profile_hash(p), build_encoder_profile_hash(q))

    def test_encoder_applies_prefix_and_normalizes(self):
        encoder = NormativeEncoder("fake", EncoderProfile("model-a", "rev-1", 4, "查询：", "条款：", normalize=True))
        vec = encoder.encode_query("通风")
        self.assertEqual(vec.shape, (4,))
        norm = float(np.linalg.norm(vec))
        self.assertAlmostEqual(norm, 1.0, places=5)
        self.assertTrue(bool(vec.tolist()))
        encoder.close()

    def test_encoder_document_prefix_visible_to_model(self):
        captured = {}

        class CapturingTransformer(FakeSentenceTransformer):
            def encode(self, texts, convert_to_numpy=True):
                captured["texts"] = list(texts)
                return super().encode(texts, convert_to_numpy=True)

        sys.modules["sentence_transformers"] = types.SimpleNamespace(
            SentenceTransformer=CapturingTransformer
        )
        encoder = NormativeEncoder("fake", EncoderProfile("model-a", "rev-1", 4, "查询：", "条款："))
        encoder.encode_documents(["通风"])
        self.assertIn("条款：", captured["texts"][0])

    def test_model_revision_deterministic(self):
        self.assertEqual(model_revision("/no/such/dir"), model_revision("/no/such/dir"))
