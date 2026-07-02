import unittest

from kg_extract_build.dashboard_run import chunking_notice, provider_form_defaults


class DashboardRunTests(unittest.TestCase):
    def test_default_chunking_notice_is_explicit(self):
        level, message = chunking_notice(2000)
        self.assertEqual(level, "info")
        self.assertIn("当前使用项目默认切片配置", message)
        self.assertIn("2000", message)

    def test_custom_chunking_notice_shows_actual_value(self):
        level, message = chunking_notice(1200)
        self.assertEqual(level, "warning")
        self.assertIn("自定义配置", message)
        self.assertIn("1200", message)

    def test_provider_defaults_do_not_return_secret(self):
        defaults = provider_form_defaults("deepseek")
        self.assertNotIn("api_key", defaults)
        self.assertEqual(defaults["base_url"], "https://api.deepseek.com")


if __name__ == "__main__":
    unittest.main()
