import unittest

from kg_extract_build.normative import ClauseDraft
from kg_extract_build.normative_segmentation import (
    build_prefix,
    segment_clause,
)


def word_tokenizer(text):
    return text.split(" ")


class SegmentationTests(unittest.TestCase):
    def test_build_prefix_joins_identity(self):
        self.assertEqual(
            build_prefix("规程", ("第二章", "2.1"), "第二十条"),
            "【规范：规程 第二章/2.1 第二十条】",
        )

    def test_short_clause_is_single_segment(self):
        clause = ClauseDraft("第二十条", ("总则",), None,
                             "作业前应通风。", "作业前应通风。", 0, 8, "structured")
        segments = segment_clause(
            clause, family_name="规程", tokenizer=word_tokenizer, max_tokens=128,
        )
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].segment_index, 0)
        self.assertIn("作业前应通风", segments[0].embedding_text)

    def test_long_clause_splits_with_prefix_and_overlap(self):
        body = " ".join(["词"] * 100)
        clause = ClauseDraft("第二十条", ("总则",), None,
                             body, body, 0, len(body), "structured")
        segments = segment_clause(
            clause, family_name="规程", tokenizer=word_tokenizer,
            max_tokens=50, overlap_tokens=5,
        )
        self.assertGreater(len(segments), 1)
        for seg in segments:
            self.assertIn("第二十条", seg.embedding_text)
            self.assertLessEqual(seg.token_count, 50)

    def test_no_segment_silently_drops_body(self):
        body = " ".join(["词"] * 100)
        clause = ClauseDraft(None, ("附录",), None, body, body, 0, len(body), "fallback")
        segments = segment_clause(
            clause, family_name="规程", tokenizer=word_tokenizer, max_tokens=30, overlap_tokens=4,
        )
        joined = " ".join(s.embedding_text for s in segments)
        self.assertGreaterEqual(len(joined.replace("【规范：规程 附录】", "").split(" ")), 100)
