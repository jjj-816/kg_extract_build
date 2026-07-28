import unittest

from kg_extract_build.normative import (
    NormativeVersionCandidate,
    applicable_versions,
    build_index_fingerprint,
    parse_normative_clauses,
)


class NormativeClauseTests(unittest.TestCase):
    def test_parses_law_and_numbered_clauses_with_full_text(self):
        text = "# 总则\n\n第二十条 作业前应通风。\n附加要求。\n\n5.1.2 应记录检测结果。\n"
        clauses = parse_normative_clauses(text)
        self.assertEqual([item.clause_number for item in clauses], ["第二十条", "5.1.2"])
        self.assertIn("附加要求", clauses[0].raw_text)
        self.assertEqual(clauses[0].hierarchy_path, ("总则",))
        self.assertEqual(clauses[0].parse_status, "structured")

    def test_unstructured_text_uses_fallback_without_inventing_numbers(self):
        clauses = parse_normative_clauses("# 附录\n\n应保存记录。\n\n不得违章作业。")
        self.assertEqual(len(clauses), 2)
        self.assertTrue(all(item.clause_number is None for item in clauses))
        self.assertTrue(all(item.parse_status == "fallback" for item in clauses))

    def test_index_fingerprint_is_stable_and_changes_with_encoder_profile(self):
        args = dict(
            document_content_hash="doc", metadata_hash="meta", clause_set_id="set-1",
            chunk_config={"max_tokens": 128}, embedding_model_revision="model-a",
            encoder_profile_hash="profile-a", embedding_dimension=384,
        )
        self.assertEqual(build_index_fingerprint(**args), build_index_fingerprint(**args))
        args["encoder_profile_hash"] = "profile-b"
        self.assertNotEqual(build_index_fingerprint(**args), build_index_fingerprint(
            document_content_hash="doc", metadata_hash="meta", clause_set_id="set-1",
            chunk_config={"max_tokens": 128}, embedding_model_revision="model-a",
            encoder_profile_hash="profile-a", embedding_dimension=384,
        ))

    def test_same_year_versions_are_both_candidates_and_flagged(self):
        versions = [
            NormativeVersionCandidate("old", "family", 2020, 2025, True, "superseded"),
            NormativeVersionCandidate("new", "family", 2025, None, True, "effective"),
            NormativeVersionCandidate("unconfirmed", "other", 2020, None, False, "pending_confirmation"),
        ]
        candidates, conflicts = applicable_versions(versions, 2025)
        self.assertEqual([item.version_id for item in candidates], ["old", "new"])
        self.assertTrue(conflicts["family"])


if __name__ == "__main__":
    unittest.main()
