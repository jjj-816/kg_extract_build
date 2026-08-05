import unittest

from kg_extract_build.normative_persistence import NormativeStore
from kg_extract_build.normative_registry import (
    guess_version_year,
    register_version,
)

from test_normative_persistence import InMemoryBackend


class NormativeRegistryTests(unittest.TestCase):
    def setUp(self):
        self.store = NormativeStore(InMemoryBackend())

    def test_guess_year_from_text(self):
        self.assertEqual(guess_version_year("2020年发布"), 2020)
        self.assertIsNone(guess_version_year("无年份"))

    def test_register_creates_family_version_clauses(self):
        content = "# 总则\n\n第二十条 作业前应通风。\n\n5.1.2 应记录检测结果。\n"
        result = register_version(
            self.store, document_id=36, file_name="有限空间作业规程.md",
            content=content, display_name="有限空间作业规程 2020",
            effective_year=2020, status="effective",
        )
        self.assertEqual(result["clause_count"], 2)
        self.assertTrue(result["family_id"])
        self.assertTrue(result["version_id"])
        self.assertTrue(result["clause_set_id"])

    def test_reparse_creates_new_clause_set_not_overwrite(self):
        content = "# 总则\n\n第二十条 作业前应通风。\n"
        first = register_version(
            self.store, document_id=36, file_name="规程.md", content=content,
            display_name="规程 2020", effective_year=2020, status="effective",
        )
        content2 = "# 总则\n\n第二十条 作业前应通风。\n\n第二十一条 严禁违章。\n"
        second = register_version(
            self.store, document_id=36, file_name="规程.md", content=content2,
            display_name="规程 2020", effective_year=2020, status="effective",
        )
        self.assertNotEqual(first["clause_set_id"], second["clause_set_id"])
        # 新条款集含两条，旧条款集仍可读（不被覆盖）
        old_clauses = self.store.get_clauses(first["clause_set_id"])
        new_clauses = self.store.get_clauses(second["clause_set_id"])
        self.assertEqual(len(old_clauses), 1)
        self.assertEqual(len(new_clauses), 2)
