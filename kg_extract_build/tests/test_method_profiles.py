import unittest

from kg_extract_build.method_profiles import METHOD_PROFILES, get_method_profile
from kg_extract_build.relation_batching import build_fixed_relation_batches


class MethodProfileTests(unittest.TestCase):
    def test_profiles_define_the_planned_r2_to_r6_methods(self):
        self.assertEqual(
            tuple(METHOD_PROFILES),
            ("R2", "R3", "R4", "R5", "R6", "D0", "D1", "D2", "D3", "D4", "D5", "D6"),
        )
        self.assertEqual(get_method_profile("R2").relation_strategy, "llm_direct")
        self.assertEqual(get_method_profile("R3").relation_strategy, "single_entity")
        self.assertEqual(get_method_profile("R4").relation_strategy, "fixed_batch")
        self.assertTrue(get_method_profile("R6").enable_schema_validation)
        self.assertFalse(get_method_profile("R5").enable_schema_validation)
        self.assertFalse(get_method_profile("D1").enable_entity_alignment)
        self.assertFalse(get_method_profile("D2").enable_llm_alignment)
        self.assertFalse(get_method_profile("D3").enable_retrieval)
        self.assertFalse(get_method_profile("D5").enable_context_deduplication)

    def test_fixed_batches_keep_entity_order_without_overlap_selection(self):
        batches = build_fixed_relation_batches(
            {
                "A": [{"sentence_index": 1, "sentence": "a"}],
                "B": [{"sentence_index": 9, "sentence": "b"}],
                "C": [{"sentence_index": 2, "sentence": "c"}],
            },
            max_entities=2,
            max_context_chars=100,
        )
        self.assertEqual([batch.entity_names for batch in batches], [("A", "B"), ("C",)])

    def test_no_deduplication_keeps_shared_evidence_twice(self):
        batches = build_fixed_relation_batches(
            {
                "A": [{"sentence_index": 1, "sentence": "shared"}],
                "B": [{"sentence_index": 1, "sentence": "shared"}],
            }, max_entities=2, max_context_chars=100,
            deduplicate_evidence=False,
        )
        self.assertEqual(len(batches[0].evidence), 2)
