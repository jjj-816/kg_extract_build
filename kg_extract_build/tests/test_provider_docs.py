import unittest
from pathlib import Path


class ProviderDocsTests(unittest.TestCase):
    def test_env_example_lists_all_online_provider_credentials(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / ".env.example").read_text(encoding="utf-8")
        for name in [
            "ZAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "DASHSCOPE_API_KEY",
            "MODELSCOPE_API_TOKEN",
            "HF_TOKEN",
        ]:
            self.assertIn(name, text)

    def test_readme_uses_single_streamlit_start_command(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "python -m streamlit run kg_extract_build/dashboard.py",
            text,
        )

    def test_env_example_documents_thinking_default(self):
        text = Path("kg_extract_build/.env.example").read_text(
            encoding="utf-8"
        )
        self.assertIn("LLM_ENABLE_THINKING=0", text)

    def test_readme_explains_ui_thinking_switch(self):
        text = Path("kg_extract_build/README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("启用思考模式", text)
        self.assertIn("默认关闭", text)


if __name__ == "__main__":
    unittest.main()
