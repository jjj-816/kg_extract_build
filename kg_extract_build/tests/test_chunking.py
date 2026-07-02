import sys
import types
import unittest
from pathlib import Path


TEST_PARENT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = TEST_PARENT.parent if TEST_PARENT.name == "kg_extract_build" else TEST_PARENT
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

sys.modules.setdefault("openai", types.SimpleNamespace(OpenAI=object))

from kg_extract_build.extractor import LongDocLLMEntityExtractor


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


if __name__ == "__main__":
    unittest.main()
