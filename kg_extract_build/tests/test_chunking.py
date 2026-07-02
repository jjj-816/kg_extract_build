import sys
import types
import unittest
from pathlib import Path
from unittest import mock


TEST_PARENT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = TEST_PARENT.parent if TEST_PARENT.name == "kg_extract_build" else TEST_PARENT
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

sys.modules.setdefault("openai", types.SimpleNamespace(OpenAI=object))

from kg_extract_build.extractor import LongDocLLMEntityExtractor


class Schema:
    pass


class ChunkingTests(unittest.TestCase):
    def test_markdown_heading_is_not_duplicated(self):
        extractor = LongDocLLMEntityExtractor.__new__(LongDocLLMEntityExtractor)
        extractor.max_chunk_size = 2000
        text = "# 第一章\n内容甲。\n## 第二节\n内容乙。"

        chunks = extractor._split_document(text)
        joined = "\n".join(chunks)

        self.assertEqual(joined.count("# 第一章"), 1)
        self.assertEqual(joined.count("## 第二节"), 1)
        self.assertIn("内容甲", joined)
        self.assertIn("内容乙", joined)

    def test_default_max_chunk_size_remains_2000(self):
        extractor = LongDocLLMEntityExtractor.__new__(LongDocLLMEntityExtractor)
        extractor.max_chunk_size = 2000
        text = "# 标题\n" + ("甲" * 2100)
        chunks = extractor._split_document(text)
        self.assertEqual(len(chunks[0]), 2000)
        self.assertEqual("".join(chunks), text)

    def test_custom_max_chunk_size_is_used(self):
        extractor = LongDocLLMEntityExtractor.__new__(LongDocLLMEntityExtractor)
        extractor.max_chunk_size = 500
        text = "甲" * 1200
        self.assertEqual(
            [len(item) for item in extractor._split_document(text)],
            [500, 500, 200],
        )

    def test_constructor_accepts_custom_max_chunk_size(self):
        with mock.patch("kg_extract_build.extractor.OpenAI"):
            extractor = LongDocLLMEntityExtractor(
                [], "key", "url", "model", Schema(), max_chunk_size=800
            )
        self.assertEqual(extractor.max_chunk_size, 800)


if __name__ == "__main__":
    unittest.main()
