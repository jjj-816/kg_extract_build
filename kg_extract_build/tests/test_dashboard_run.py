import unittest

from kg_extract_build.dashboard_run import (
    PIPELINE_STAGE_LABELS,
    build_llm_config,
    chunking_notice,
    provider_form_defaults,
    relation_strategy_notice,
    thinking_mode_notice,
)


class DashboardRunTests(unittest.TestCase):
    def test_pipeline_stages_include_preprocessing_before_chunking(self):
        stages = [stage for stage, _label in PIPELINE_STAGE_LABELS]
        assert stages.index("preprocessing") < stages.index("chunking")

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

    def test_relation_strategy_notice_distinguishes_batch_and_baseline(self):
        self.assertIn(
            "共享上下文",
            relation_strategy_notice("shared_context_batch"),
        )
        self.assertIn(
            "基线",
            relation_strategy_notice("single_entity"),
        )

    def test_thinking_notice_explains_default_cost_behavior(self):
        message = thinking_mode_notice(False)
        self.assertIn("默认关闭", message)
        self.assertIn("Token", message)

    def test_dashboard_llm_config_forwards_thinking_choice(self):
        config = build_llm_config(
            provider_id="qwen",
            api_key="secret",
            base_url="https://example.test/v1",
            model="qwen-plus",
            enable_thinking=True,
        )
        self.assertTrue(config.enable_thinking)


if __name__ == "__main__":
    unittest.main()
