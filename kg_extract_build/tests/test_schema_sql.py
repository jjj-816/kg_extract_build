import re
import unittest
from pathlib import Path


class SchemaSqlTests(unittest.TestCase):
    def _schema_sql(self):
        test_parent = Path(__file__).resolve().parents[1]
        package_dir = (
            test_parent
            if test_parent.name == "kg_extract_build"
            else test_parent / "kg_extract_build"
        )
        return (package_dir / "schema.sql").read_text(encoding="utf-8")

    def test_contains_expected_tables(self):
        sql = self._schema_sql()
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
                "kg_triplet_evidence",
                "kg_evaluation_run",
                "kg_evaluation_metric",
                "kg_evaluation_entity_alignment",
            },
        )

    def test_evaluation_tables_are_declared(self):
        schema_sql = self._schema_sql()
        self.assertIn("CREATE TABLE IF NOT EXISTS kg_evaluation_run", schema_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS kg_evaluation_metric", schema_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS kg_evaluation_entity_alignment", schema_sql)
        self.assertIn("gold_hash CHAR(64) NOT NULL", schema_sql)
        self.assertIn("INDEX idx_kg_eval_run_gold (run_id, gold_hash)", schema_sql)
        self.assertIn("CONSTRAINT fk_kg_eval_run FOREIGN KEY (run_id)", schema_sql)
        self.assertIn("CONSTRAINT fk_kg_eval_metric_run FOREIGN KEY (evaluation_id)", schema_sql)


if __name__ == "__main__":
    unittest.main()
