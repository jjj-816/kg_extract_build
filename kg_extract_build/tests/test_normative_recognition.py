import unittest
from types import SimpleNamespace

from kg_extract_build.audit.normative_recognition import freeze_confirmed_candidates, recognize_declared_norms


class NormativeRecognitionTests(unittest.TestCase):
    def test_pairs_book_titles_with_adjacent_codes_and_ignores_reference_number(self):
        text = (
            "依据 2\n"
            "《页岩气地面工程设计规范》Q/SY1858-2015\n"
            "《石油天然气工程设计防火规范》GB50183-2004"
        )
        candidates = recognize_declared_norms([SimpleNamespace(block_id="b1", source_locator="p1", raw_text=text)])
        self.assertEqual(
            [item.value for item in candidates],
            ["《页岩气地面工程设计规范》Q/SY1858-2015", "《石油天然气工程设计防火规范》GB50183-2004"],
        )

    def test_extracts_books_codes_and_reference_phrases_with_evidence(self):
        candidates = recognize_declared_norms([SimpleNamespace(block_id="b1", source_locator="p1", raw_text="依据《建筑施工安全检查标准》JGJ 59-2011，按照 GB/T 50430-2017 执行。")])
        self.assertGreaterEqual(len(candidates), 2)
        self.assertTrue(all(item.source_block_id == "b1" and item.evidence_text for item in candidates))

    def test_freeze_keeps_only_confirmed_candidates(self):
        candidates = recognize_declared_norms([SimpleNamespace(block_id="b1", source_locator="p1", raw_text="依据《安全规范》")])
        frozen = freeze_confirmed_candidates(candidates, [candidates[0].candidate_id])
        self.assertEqual(len(frozen), 1)
        self.assertTrue(frozen[0]["confirmed"])
        self.assertEqual(freeze_confirmed_candidates(candidates, ["missing"]), ())


if __name__ == "__main__":
    unittest.main()
