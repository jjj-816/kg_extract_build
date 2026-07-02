import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class DashboardSmokeTests(unittest.TestCase):
    def test_default_run_page_starts_without_mysql_connection(self):
        dashboard = Path(__file__).resolve().parents[1] / "dashboard.py"
        app = AppTest.from_file(str(dashboard)).run(timeout=15)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(
            any(
                title.value == "运行实体提取实验"
                for title in app.title
            )
        )


if __name__ == "__main__":
    unittest.main()
