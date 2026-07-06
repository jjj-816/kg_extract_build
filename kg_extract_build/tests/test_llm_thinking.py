import unittest

from kg_extract_build.llm_thinking import build_thinking_options, is_thinking_only_model


class LLMThinkingOptionsTests(unittest.TestCase):
    def test_provider_options_explicitly_disable_thinking(self):
        expected = {
            "zhipu": {
                "extra_body": {"thinking": {"type": "disabled"}}
            },
            "deepseek": {
                "extra_body": {"thinking": {"type": "disabled"}}
            },
            "qwen": {"extra_body": {"enable_thinking": False}},
            "modelscope": {
                "extra_body": {"enable_thinking": False}
            },
            "ollama": {"reasoning_effort": "none"},
            "huggingface": {"reasoning_effort": "none"},
            "custom": {"reasoning_effort": "none"},
        }
        for provider_id, options in expected.items():
            with self.subTest(provider_id=provider_id):
                self.assertEqual(
                    build_thinking_options(provider_id, False),
                    options,
                )

    def test_provider_options_enable_thinking_only_when_requested(self):
        expected = {
            "zhipu": {
                "extra_body": {"thinking": {"type": "enabled"}}
            },
            "deepseek": {
                "extra_body": {"thinking": {"type": "enabled"}}
            },
            "qwen": {"extra_body": {"enable_thinking": True}},
            "modelscope": {
                "extra_body": {"enable_thinking": True}
            },
            "ollama": {"reasoning_effort": "high"},
            "huggingface": {"reasoning_effort": "high"},
            "custom": {"reasoning_effort": "high"},
        }
        for provider_id, options in expected.items():
            with self.subTest(provider_id=provider_id):
                self.assertEqual(
                    build_thinking_options(provider_id, True),
                    options,
                )

    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知"):
            build_thinking_options("missing", False)


class ThinkingOnlyModelTests(unittest.TestCase):
    def test_known_thinking_only_models_are_detected(self):
        cases = (
            ("deepseek", "deepseek-reasoner"),
            ("huggingface", "deepseek-ai/DeepSeek-R1"),
            ("qwen", "QwQ-32B"),
            ("modelscope", "Qwen3-32B-Thinking"),
            ("ollama", "gpt-oss:20b"),
        )
        for provider_id, model in cases:
            with self.subTest(model=model):
                self.assertTrue(
                    is_thinking_only_model(provider_id, model)
                )

    def test_hybrid_or_non_thinking_models_are_not_rejected(self):
        cases = (
            ("deepseek", "deepseek-chat"),
            ("zhipu", "glm-4.5-air"),
            ("qwen", "qwen-plus"),
            ("ollama", "qwen3:8b"),
        )
        for provider_id, model in cases:
            with self.subTest(model=model):
                self.assertFalse(
                    is_thinking_only_model(provider_id, model)
                )
