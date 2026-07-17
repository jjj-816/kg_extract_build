import sys
import unittest
from pathlib import Path


TEST_PARENT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = TEST_PARENT.parent if TEST_PARENT.name == "kg_extract_build" else TEST_PARENT
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from kg_extract_build.dashboard_evaluation import _metric_row, format_run_label


class DashboardEvaluationTests(unittest.TestCase):
    def test_format_run_label_contains_name_and_status(self):
        label = format_run_label(
            {
                "run_id": "abc123",
                "run_name": "实验一",
                "status": "completed",
                "started_at": "2026-07-09 10:00:00",
            }
        )
        self.assertIn("实验一", label)
        self.assertIn("completed", label)
        self.assertIn("abc123", label)

    def test_metric_row_has_chinese_label_and_description(self):
        row = _metric_row("canonical_triplet_f1", 0.5, None, None)
        self.assertEqual(row["\u539f\u59cb\u5b57\u6bb5"], "canonical_triplet_f1")
        self.assertIn("\u89c4\u8303\u5316", row["\u4e2d\u6587\u6307\u6807"])
        self.assertTrue(row["\u6307\u6807\u8bf4\u660e"])


if __name__ == "__main__":
    unittest.main()
