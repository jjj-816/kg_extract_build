import re
import unittest
from pathlib import Path


class SchemaSqlTests(unittest.TestCase):
    def test_contains_expected_seven_tables(self):
        test_parent = Path(__file__).resolve().parents[1]
        package_dir = (
            test_parent
            if test_parent.name == "kg_extract_build"
            else test_parent / "kg_extract_build"
        )
        schema_path = package_dir / "schema.sql"
        sql = schema_path.read_text(encoding="utf-8")
        tables = set(
            re.findall(
                r"CREATE TABLE IF NOT EXISTS\s+([a-z_]+)",
                sql,
                flags=re.IGNORECASE,
            )
        )
        self.assertEqual(
            tables,
            {
                "kg_experiment_run",
                "kg_document",
                "kg_document_chunk",
                "kg_llm_call",
                "kg_entity",
                "kg_retrieval_result",
                "kg_triplet",
            },
        )


if __name__ == "__main__":
    unittest.main()
