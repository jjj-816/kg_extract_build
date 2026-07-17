import io
import json
import zipfile
import unittest

from kg_extract_build.experiment_export import build_experiment_package


class ExperimentExportTests(unittest.TestCase):
    def test_package_contains_reproducibility_data_and_csvs(self):
        package, counts = build_experiment_package({
            "run": {"run_id": "run-1", "code_commit": "abc", "config_snapshot": {"method_id": "R6"}},
            "documents": [{"document_id": 1, "content": "正文"}],
            "final_triplets": [{"head": "井口", "relation_name": "USES", "tail": "设备"}],
        })
        self.assertEqual(counts["documents"], 1)
        self.assertEqual(counts["final_triplets"], 1)
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            self.assertIn("README_导出说明.md", archive.namelist())
            self.assertIn("00_运行信息.json", archive.namelist())
            self.assertIn("07_最终三元组.csv", archive.namelist())
            run = json.loads(archive.read("00_运行信息.json"))
            self.assertEqual(run["config_snapshot"]["method_id"], "R6")
            triples = archive.read("07_最终三元组.csv").decode("utf-8-sig")
            self.assertIn("井口", triples)


if __name__ == "__main__":
    unittest.main()
