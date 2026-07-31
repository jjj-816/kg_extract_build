import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class AuditDashboardTests(unittest.TestCase):
    def test_audit_page_is_available_without_mysql_connection(self):
        dashboard = Path(__file__).resolve().parents[1] / "dashboard.py"
        app = AppTest.from_file(str(dashboard)).run(timeout=15)
        app.sidebar.radio[0].set_value("施工方案审核").run(timeout=15)

        self.assertEqual(list(app.exception), [])
        self.assertTrue(any(title.value == "施工方案审核" for title in app.title))
        self.assertTrue(any(item.label == "输入已创建的 run_id" for item in app.text_input))


if __name__ == "__main__":
    unittest.main()
