import sys
import types
import unittest
from pathlib import Path


TEST_PARENT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = TEST_PARENT.parent if TEST_PARENT.name == "kg_extract_build" else TEST_PARENT
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

sys.modules.setdefault("openai", types.SimpleNamespace(OpenAI=object))

from kg_extract_build.preprocess import is_valid_entity_candidate, preprocess_document
from kg_extract_build.settings import UNKNOWN_TYPE
from kg_extract_build.triplets import TripletCorrector, TripletGenerator
from kg_extract_build.extractor import LongDocLLMEntityExtractor


class MarkdownPreprocessTests(unittest.TestCase):
    def test_removes_images_sequence_lines_and_certificate_numbers_but_keeps_parameter_sentence(self):
        text = (
            "# 施工方案\n"
            "![image](https://cdn.example.test/image.jpg)\n"
            "14）回填完成后进行硬化\n"
            "证件号：511526199601293615\n"
            "试吊高度为 10cm。\n"
        )

        result = preprocess_document(text)

        self.assertIn("# 施工方案", result.clean_text)
        self.assertIn("试吊高度为 10cm", result.clean_text)
        self.assertNotIn("![image]", result.clean_text)
        self.assertNotIn("14）", result.clean_text)
        self.assertNotIn("511526199601293615", result.clean_text)
        self.assertEqual(result.stats["image_markdown_count"], 1)
        self.assertEqual(result.stats["removed_sequence_line_count"], 1)
        self.assertEqual(result.stats["redacted_identifier_count"], 1)

    def test_rejects_numeric_candidates_but_keeps_parameter_names(self):
        self.assertFalse(is_valid_entity_candidate("12"))
        self.assertFalse(is_valid_entity_candidate("10cm"))
        self.assertFalse(is_valid_entity_candidate("2025\u5e7412\u6708"))
        self.assertTrue(is_valid_entity_candidate("\u8bd5\u540a\u9ad8\u5ea6"))


class ExtractorCandidateGuardTests(unittest.TestCase):
    def test_extractor_drops_numeric_candidates_before_alignment(self):
        extractor = LongDocLLMEntityExtractor.__new__(LongDocLLMEntityExtractor)
        result = extractor._filter_invalid_entities(
            [
                {"name": "12", "type": "????"},
                {"name": "10cm", "type": "????"},
                {"name": "????", "type": "????"},
            ]
        )

        self.assertEqual(result, [{"name": "????", "type": "????"}])


class TripletParsingGuardTests(unittest.TestCase):
    class Schema:
        def normalize_relation(self, value):
            return value

        def normalize_entity_type(self, value):
            return value

        def is_relation_allowed(self, relation, head_type, tail_type):
            return True

    def test_parser_rejects_numeric_head_before_raw_triplets_are_recorded(self):
        generator = TripletGenerator.__new__(TripletGenerator)
        generator.schema = self.Schema()
        generator.known_entities = {}

        result = generator._parse_triplets(
            '[{"head": "12", "relation": "RECORDED_IN", "tail": "record", "tail_type": "record_type"}]',
            "12",
            "parameter_type",
            "12 record",
        )

        self.assertEqual(result, [])


class TripletNoiseGuardTests(unittest.TestCase):
    class Schema:
        def normalize_entity_type(self, value):
            return value

        def is_final_entity_type_allowed(self, value):
            return bool(value) and value != UNKNOWN_TYPE

        def is_relation_allowed(self, relation, head_type, tail_type):
            return True

    def test_rejects_numeric_head_but_allows_numeric_parameter_value(self):
        corrector = TripletCorrector(self.Schema())
        result = corrector.correct(
            {
                "12": [{"head": "12", "head_type": "????", "relation": "RECORDED_IN", "tail": "??", "tail_type": "????"}],
                "????": [{"head": "????", "head_type": "????", "relation": "HAS_THRESHOLD", "tail": "10cm", "tail_type": "????"}],
            }
        )

        self.assertEqual(result, [("????", "????", "HAS_THRESHOLD", "10cm", "????")])


if __name__ == "__main__":
    unittest.main()
