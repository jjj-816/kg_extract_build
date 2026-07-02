import json
import os
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from kg_extract_build import run_config
except (ImportError, ModuleNotFoundError):
    run_config = None


@unittest.skipIf(run_config is None, "run_config module is not implemented yet")
class RunConfigTests(unittest.TestCase):
    def make_config(
        self,
        folder,
        *,
        selected_files=("document.md",),
        provider_id="deepseek",
        api_key="secret-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        max_chars=2000,
    ):
        return run_config.PipelineConfig(
            run_name="test-run",
            document_folder=Path(folder),
            selected_files=selected_files,
            llm=run_config.LLMConfig(
                provider_id=provider_id,
                api_key=api_key,
                base_url=base_url,
                model=model,
            ),
            chunking=run_config.ChunkingConfig(max_chars=max_chars),
        )

    def test_provider_ids_and_presets_are_stable(self):
        self.assertEqual(
            set(run_config.PROVIDERS),
            {
                "zhipu",
                "deepseek",
                "ollama",
                "qwen",
                "modelscope",
                "huggingface",
                "custom",
            },
        )
        self.assertEqual(
            run_config.PROVIDERS["zhipu"].env_keys,
            ("ZAI_API_KEY", "LLM_API_KEY"),
        )
        self.assertEqual(
            run_config.PROVIDERS["custom"].default_base_url,
            os.environ.get("LLM_BASE_URL", ""),
        )
        self.assertFalse(run_config.PROVIDERS["ollama"].requires_api_key)

    def test_provider_preset_is_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            run_config.PROVIDERS["deepseek"].label = "changed"

    def test_api_key_override_takes_precedence(self):
        key = run_config.resolve_provider_api_key(
            "deepseek",
            override="temporary",
            environ={"DEEPSEEK_API_KEY": "environment"},
        )
        self.assertEqual(key, "temporary")

    def test_zhipu_falls_back_to_llm_api_key(self):
        key = run_config.resolve_provider_api_key(
            "zhipu",
            environ={"ZAI_API_KEY": "", "LLM_API_KEY": "fallback"},
        )
        self.assertEqual(key, "fallback")

    def test_ollama_uses_non_secret_placeholder(self):
        self.assertEqual(
            run_config.resolve_provider_api_key("ollama", environ={}),
            "ollama",
        )

    def test_unknown_provider_key_lookup_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "提供商"):
            run_config.resolve_provider_api_key("missing", environ={})

    def test_redact_text_removes_explicit_secrets_and_bearer_tokens(self):
        text = (
            "api_key=top-secret\n"
            "Authorization: Bearer header-secret\n"
            "request used Bearer inline-secret"
        )
        redacted = run_config.redact_text(
            text,
            secrets=("top", "top-secret"),
        )
        self.assertNotIn("top-secret", redacted)
        self.assertIn("api_key=***\n", redacted)
        self.assertNotIn("header-secret", redacted)
        self.assertNotIn("inline-secret", redacted)
        self.assertIn("Authorization: Bearer ***", redacted)
        self.assertIn("Bearer ***", redacted)

    def test_sanitized_snapshot_never_contains_api_key(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text("content", encoding="utf-8")
            config = self.make_config(folder, api_key="snapshot-secret")

            snapshot = config.sanitized_snapshot()
            serialized = json.dumps(snapshot, ensure_ascii=False)

            self.assertNotIn("snapshot-secret", serialized)
            self.assertNotIn("api_key", snapshot["llm"])
            self.assertTrue(snapshot["llm"]["api_key_configured"])
            self.assertEqual(snapshot["chunking"]["max_chars"], 2000)
            self.assertEqual(snapshot["retrieve_sentence_num"], 10)
            self.assertFalse(snapshot["respect_legacy_breakpoint"])
            self.assertFalse(snapshot["reuse_entity_cache"])
            self.assertFalse(snapshot["reuse_triplet_cache"])

    def test_online_provider_requires_api_key(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text("content", encoding="utf-8")
            config = self.make_config(folder, api_key="")
            with self.assertRaisesRegex(ValueError, "API Key"):
                config.validate()

    def test_online_provider_rejects_whitespace_api_key(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text("content", encoding="utf-8")
            config = self.make_config(folder, api_key="   ")
            with self.assertRaisesRegex(ValueError, "API Key"):
                config.validate()

    def test_chunk_range_is_checked_before_selected_file_existence(self):
        with tempfile.TemporaryDirectory() as folder:
            config = self.make_config(
                folder,
                selected_files=("missing.md",),
                max_chars=199,
            )
            with self.assertRaisesRegex(ValueError, "200"):
                config.validate()

    def test_valid_direct_markdown_file_passes_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text("# title", encoding="utf-8")
            config = self.make_config(folder)
            self.assertIsNone(config.validate())

    def test_path_like_selected_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            subfolder = Path(folder, "sub")
            subfolder.mkdir()
            Path(subfolder, "document.md").write_text("content", encoding="utf-8")
            config = self.make_config(
                folder,
                selected_files=("sub/document.md",),
            )
            with self.assertRaisesRegex(ValueError, "文件名"):
                config.validate()


class RunConfigAvailabilityTests(unittest.TestCase):
    def test_run_config_module_exists(self):
        self.assertIsNotNone(run_config, "kg_extract_build.run_config is missing")


if __name__ == "__main__":
    unittest.main()
