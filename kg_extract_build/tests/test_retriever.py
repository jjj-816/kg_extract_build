import sys
import types
import unittest
from pathlib import Path

import numpy as np


TEST_PARENT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = TEST_PARENT.parent if TEST_PARENT.name == "kg_extract_build" else TEST_PARENT
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))


class FakeSentenceTransformer:
    def __init__(self, _model_path):
        pass

    def encode(self, texts, convert_to_numpy=True):
        vectors = []
        for text in texts:
            vectors.append([1.0, 0.0] if "井口" in text else [0.0, 1.0])
        return np.asarray(vectors, dtype=float)


sys.modules["sentence_transformers"] = types.SimpleNamespace(
    SentenceTransformer=FakeSentenceTransformer
)

from kg_extract_build.retriever import CorpusRetriever


class RetrieverTests(unittest.TestCase):
    def test_exports_offsets_and_detailed_hits(self):
        corpus = "井口需要定期检测。无关句子足够长用于测试。"
        retriever = CorpusRetriever(corpus, "fake", top_n=2)

        segments = retriever.export_segments()
        hits = retriever.retrieve_with_details("井口")

        self.assertEqual(segments[0]["start_offset"], 0)
        self.assertEqual(segments[0]["content"], "井口需要定期检测")
        self.assertEqual(hits[0]["sentence_index"], 0)
        self.assertEqual(hits[0]["match_type"], "direct")
        self.assertEqual(hits[0]["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
