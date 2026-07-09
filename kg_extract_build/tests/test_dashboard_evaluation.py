import sys
import unittest
from pathlib import Path


TEST_PARENT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = TEST_PARENT.parent if TEST_PARENT.name == "kg_extract_build" else TEST_PARENT
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from kg_extract_build.dashboard_evaluation import format_run_label


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


if __name__ == "__main__":
    unittest.main()
