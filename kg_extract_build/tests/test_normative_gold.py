import unittest
from pathlib import Path

from kg_extract_build.normative import parse_normative_clauses


class GoldClauseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = Path(__file__).with_name("fixtures") / "spec_clause_gold.md"
        cls.text = fixture.read_text(encoding="utf-8")

    def test_gold_parses_law_and_numbered_clauses(self):
        clauses = parse_normative_clauses(self.text)
        numbers = [c.clause_number for c in clauses]
        self.assertEqual(numbers, ["第二十条", "第二十一条", "5.1.2"])

    def test_multi_paragraph_merges_into_one_clause(self):
        clauses = parse_normative_clauses(self.text)
        c20 = next(c for c in clauses if c.clause_number == "第二十条")
        self.assertIn("作业票审批记录", c20.raw_text)

    def test_markdown_table_stays_in_clause(self):
        clauses = parse_normative_clauses(self.text)
        self.assertTrue(any("通风时间" in c.raw_text for c in clauses))

    def test_fallback_for_unstructured_section(self):
        clauses = parse_normative_clauses("附录\n\n应保存记录。\n\n不得违章作业。")
        self.assertTrue(all(c.clause_number is None for c in clauses))
        self.assertTrue(all(c.parse_status == "fallback" for c in clauses))


if __name__ == "__main__":
    unittest.main()
