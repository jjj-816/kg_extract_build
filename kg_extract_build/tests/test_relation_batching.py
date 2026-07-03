import unittest

from kg_extract_build.relation_batching import (
    build_relation_batches,
    overlap_coefficient,
)


def hit(index, sentence=None, score=1.0):
    return {
        "sentence_index": index,
        "sentence": sentence or f"证据句{index}",
        "score": score,
        "match_type": "direct",
    }


class RelationBatchingTests(unittest.TestCase):
    def test_overlap_coefficient_uses_smaller_evidence_set(self):
        self.assertEqual(
            overlap_coefficient({1, 2}, {1, 2, 3, 4}),
            1.0,
        )
        self.assertEqual(overlap_coefficient(set(), {1}), 0.0)

    def test_grouping_requires_pairwise_overlap(self):
        batches = build_relation_batches(
            {
                "A": [hit(1), hit(2)],
                "B": [hit(1), hit(2), hit(3)],
                "C": [hit(3), hit(4)],
                "D": [hit(9)],
            },
            max_entities=3,
            min_overlap=0.4,
            max_context_chars=8000,
        )

        self.assertEqual(
            [batch.entity_names for batch in batches],
            [("A", "B"), ("C",), ("D",)],
        )

    def test_evidence_is_deduplicated_and_entity_mapping_is_preserved(self):
        batches = build_relation_batches(
            {
                "井口": [hit(12), hit(13)],
                "防喷器": [hit(12), hit(13), hit(25)],
            },
            max_entities=3,
            min_overlap=0.4,
            max_context_chars=8000,
        )

        batch = batches[0]
        self.assertEqual(
            [item["sentence_index"] for item in batch.evidence],
            [12, 13, 25],
        )
        self.assertEqual(
            batch.entity_evidence_ids,
            {"井口": (12, 13), "防喷器": (12, 13, 25)},
        )

    def test_entity_limit_and_context_limit_split_batches(self):
        entity_limited = build_relation_batches(
            {
                "A": [hit(1)],
                "B": [hit(1)],
                "C": [hit(1)],
            },
            max_entities=2,
            min_overlap=0.4,
            max_context_chars=8000,
        )
        self.assertEqual(
            [batch.entity_names for batch in entity_limited],
            [("A", "B"), ("C",)],
        )

        context_limited = build_relation_batches(
            {
                "A": [hit(1, "共同证据"), hit(2, "A" * 20)],
                "B": [hit(1, "共同证据"), hit(3, "B" * 20)],
            },
            max_entities=3,
            min_overlap=0.4,
            max_context_chars=30,
        )
        self.assertEqual(
            [batch.entity_names for batch in context_limited],
            [("A",), ("B",)],
        )


if __name__ == "__main__":
    unittest.main()
