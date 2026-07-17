import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest import mock
from unittest.mock import Mock, patch


PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

try:
    from kg_extract_build import run_config
except (ImportError, ModuleNotFoundError):
    run_config = None


RUN_CONFIG_PATH = (
    PACKAGE_PARENT
    / "kg_extract_build"
    / "run_config.py"
)


def load_isolated_run_config(dotenv_module):
    module_name = "_isolated_run_config_for_tests"
    spec = importlib.util.spec_from_file_location(module_name, RUN_CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {module_name: module, "dotenv": dotenv_module},
    ):
        spec.loader.exec_module(module)
    return module


@unittest.skipIf(run_config is None, "run_config module is not implemented yet")
class RunConfigTests(unittest.TestCase):
    def make_config(
        self,
        folder,
        *,
        run_name="test-run",
        selected_files=("document.md",),
        provider_id="deepseek",
        api_key="secret-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        max_chars=2000,
    ):
        return run_config.PipelineConfig(
            run_name=run_name,
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

    def test_each_provider_has_exact_stable_preset(self):
        expected = {
            "zhipu": (
                "https://open.bigmodel.cn/api/paas/v4/",
                ("ZAI_API_KEY", "LLM_API_KEY"),
                True,
            ),
            "deepseek": (
                "https://api.deepseek.com",
                ("DEEPSEEK_API_KEY", "LLM_API_KEY"),
                True,
            ),
            "ollama": (
                "http://localhost:11434/v1/",
                (),
                False,
            ),
            "qwen": (
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
                ("DASHSCOPE_API_KEY",),
                True,
            ),
            "modelscope": (
                "https://api-inference.modelscope.cn/v1",
                ("MODELSCOPE_API_TOKEN",),
                True,
            ),
            "huggingface": (
                "https://router.huggingface.co/v1",
                ("HF_TOKEN",),
                True,
            ),
            "custom": (
                os.environ.get("LLM_BASE_URL", ""),
                ("LLM_API_KEY",),
                True,
            ),
        }

        self.assertEqual(set(run_config.PROVIDERS), set(expected))
        for provider_id, values in expected.items():
            with self.subTest(provider_id=provider_id):
                preset = run_config.PROVIDERS[provider_id]
                self.assertEqual(preset.provider_id, provider_id)
                self.assertEqual(
                    (
                        preset.default_base_url,
                        preset.env_keys,
                        preset.requires_api_key,
                    ),
                    values,
                )

    def test_custom_base_url_is_read_from_environment_at_import(self):
        fake_dotenv = types.ModuleType("dotenv")
        fake_dotenv.load_dotenv = Mock()

        with patch.dict(
            os.environ,
            {"LLM_BASE_URL": "http://custom.example/v1"},
            clear=False,
        ):
            isolated = load_isolated_run_config(fake_dotenv)

        self.assertEqual(
            isolated.PROVIDERS["custom"].default_base_url,
            "http://custom.example/v1",
        )

    def test_dotenv_loads_package_env_without_overriding_environment(self):
        fake_dotenv = types.ModuleType("dotenv")
        fake_dotenv.load_dotenv = Mock()

        load_isolated_run_config(fake_dotenv)

        fake_dotenv.load_dotenv.assert_called_once_with(
            RUN_CONFIG_PATH.with_name(".env"),
            override=False,
        )

    def test_module_import_succeeds_when_dotenv_is_unavailable(self):
        isolated = load_isolated_run_config(None)

        self.assertEqual(
            isolated.PROVIDERS["deepseek"].provider_id,
            "deepseek",
        )

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

    def test_every_key_requiring_provider_returns_empty_when_unconfigured(self):
        required_provider_ids = {
            provider_id
            for provider_id, preset in run_config.PROVIDERS.items()
            if preset.requires_api_key
        }
        self.assertEqual(
            required_provider_ids,
            {
                "zhipu",
                "deepseek",
                "qwen",
                "modelscope",
                "huggingface",
                "custom",
            },
        )
        for provider_id in required_provider_ids:
            with self.subTest(provider_id=provider_id):
                self.assertEqual(
                    run_config.resolve_provider_api_key(
                        provider_id,
                        override="",
                        environ={},
                    ),
                    "",
                )

    def test_unknown_provider_key_lookup_is_rejected(self):
        with self.assertRaises(ValueError):
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

    def test_all_runtime_configs_are_frozen_and_key_is_hidden_from_repr(self):
        llm = run_config.LLMConfig(
            provider_id="deepseek",
            api_key="repr-secret",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
        )
        chunking = run_config.ChunkingConfig()
        pipeline = run_config.PipelineConfig(
            run_name="test-run",
            document_folder=Path("."),
            selected_files=("document.md",),
            llm=llm,
            chunking=chunking,
        )

        self.assertNotIn("repr-secret", repr(llm))
        self.assertNotIn("api_key", repr(llm))
        with self.assertRaises(FrozenInstanceError):
            llm.model = "changed"
        with self.assertRaises(FrozenInstanceError):
            chunking.max_chars = 3000
        with self.assertRaises(FrozenInstanceError):
            pipeline.run_name = "changed"

    def test_chunking_defaults_are_stable(self):
        chunking = run_config.ChunkingConfig()

        self.assertEqual(chunking.strategy, "markdown_heading")
        self.assertEqual(chunking.max_chars, 2000)

    def test_relation_batch_defaults_are_effect_first(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text(
                "content", encoding="utf-8"
            )
            config = self.make_config(folder)

            self.assertEqual(
                config.relation_strategy,
                "shared_context_batch",
            )
            self.assertEqual(config.relation_batch_max_entities, 3)
            self.assertEqual(config.relation_batch_min_overlap, 0.4)
            self.assertEqual(
                config.relation_batch_max_context_chars,
                8000,
            )

    def test_relation_batch_parameters_are_validated_and_snapshotted(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text(
                "content", encoding="utf-8"
            )
            config = self.make_config(folder)
            snapshot = config.sanitized_snapshot()

        self.assertEqual(
            snapshot["relation_batch"],
                {
                    "strategy": "shared_context_batch",
                    "max_entities": 3,
                    "min_overlap": 0.4,
                    "max_context_chars": 8000,
                },
            )
        invalid_configs = (
            replace(config, relation_strategy="missing"),
            replace(config, relation_batch_max_entities=0),
            replace(config, relation_batch_min_overlap=1.1),
            replace(config, relation_batch_max_context_chars=999),
        )
        for invalid in invalid_configs:
            with self.subTest(config=invalid):
                with self.assertRaises(ValueError):
                    invalid.validate()

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

    def test_sanitized_snapshot_redacts_key_from_run_name_and_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text("content", encoding="utf-8")
            config = self.make_config(
                folder,
                run_name="实验-sk-leaked-密钥",
                api_key="sk-leaked",
            )
            snapshot = config.sanitized_snapshot()
            serialized = json.dumps(snapshot, ensure_ascii=False)
            self.assertNotIn("sk-leaked", serialized)
            self.assertIn("***", snapshot["run_name"])

    def test_sanitized_snapshot_redacts_key_from_selected_file_names(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "report-sk-leaked.md").write_text(
                "content", encoding="utf-8"
            )
            config = self.make_config(
                folder,
                selected_files=("report-sk-leaked.md",),
                api_key="sk-leaked",
            )

            serialized = json.dumps(
                config.sanitized_snapshot(), ensure_ascii=False
            )

            self.assertNotIn("sk-leaked", serialized)

    def test_sanitized_snapshot_redacts_key_from_base_url(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text("content", encoding="utf-8")
            config = self.make_config(
                folder,
                api_key="sk-leaked",
                base_url="https://sk-leaked@api.deepseek.com/v1/",
                model="sk-leaked-model",
            )

            snapshot = config.sanitized_snapshot()
            serialized = json.dumps(snapshot, ensure_ascii=False)

            self.assertNotIn("sk-leaked", serialized)
            self.assertIn("***@api.deepseek.com", snapshot["llm"]["base_url"])
            self.assertIn("***-model", snapshot["llm"]["model"])

    def test_key_override_is_stripped_of_surrounding_whitespace(self):
        self.assertEqual(
            run_config.resolve_provider_api_key(
                "deepseek",
                override="  sk-abc  ",
                environ={},
            ),
            "sk-abc",
        )

    def test_method_profile_is_saved_with_reproducibility_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text("content", encoding="utf-8")
            snapshot = self.make_config(folder).sanitized_snapshot()
        self.assertEqual(snapshot["method_id"], "R6")
        self.assertEqual(snapshot["prompt_version"], "relation-batch-v1")
        self.assertTrue(snapshot["enable_schema_validation"])
        self.assertEqual(snapshot["llm"]["temperature"], 0.1)

    def test_key_from_environment_is_stripped(self):
        self.assertEqual(
            run_config.resolve_provider_api_key(
                "deepseek",
                environ={"DEEPSEEK_API_KEY": "  sk-env  "},
            ),
            "sk-env",
        )

    def test_whitespace_only_override_falls_back_to_environment(self):
        self.assertEqual(
            run_config.resolve_provider_api_key(
                "deepseek",
                override="   ",
                environ={"DEEPSEEK_API_KEY": "sk-env"},
            ),
            "sk-env",
        )

    def test_pipeline_config_uses_default_chunking_when_omitted(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text("content", encoding="utf-8")
            config = run_config.PipelineConfig(
                run_name="default-chunking",
                document_folder=Path(folder),
                selected_files=("document.md",),
                llm=run_config.LLMConfig(
                    provider_id="deepseek",
                    api_key="secret",
                    base_url="https://api.deepseek.com",
                    model="deepseek-chat",
                ),
            )

            self.assertEqual(config.chunking.strategy, "markdown_heading")
            self.assertEqual(config.chunking.max_chars, 2000)
            self.assertIsNone(config.validate())

    def test_online_provider_requires_api_key(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text("content", encoding="utf-8")
            for value in ("", "   "):
                with self.subTest(api_key=value):
                    config = self.make_config(folder, api_key=value)
                    with self.assertRaisesRegex(ValueError, "API Key"):
                        config.validate()

    def test_validate_rejects_blank_base_url_and_model(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text("content", encoding="utf-8")
            cases = (
                {"base_url": "", "model": "deepseek-chat"},
                {"base_url": "https://api.deepseek.com", "model": ""},
            )
            for values in cases:
                with self.subTest(values=values):
                    config = self.make_config(folder, **values)
                    with self.assertRaises(ValueError):
                        config.validate()

    def test_validate_rejects_empty_selected_files(self):
        with tempfile.TemporaryDirectory() as folder:
            config = self.make_config(folder, selected_files=())

            with self.assertRaises(ValueError):
                config.validate()

    def test_validate_rejects_invalid_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            missing_folder = Path(folder, "missing")
            config = self.make_config(missing_folder)

            with self.assertRaises(ValueError):
                config.validate()

    def test_validate_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            config = self.make_config(folder, selected_files=("missing.md",))

            with self.assertRaises(ValueError):
                config.validate()

    def test_validate_rejects_unsupported_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.pdf").write_text("content", encoding="utf-8")
            config = self.make_config(
                folder,
                selected_files=("document.pdf",),
            )

            with self.assertRaises(ValueError):
                config.validate()

    def test_chunk_boundaries_are_inclusive_and_outside_values_fail_first(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text("content", encoding="utf-8")
            for max_chars in (200, 20_000):
                with self.subTest(max_chars=max_chars):
                    self.assertIsNone(
                        self.make_config(
                            folder,
                            max_chars=max_chars,
                        ).validate()
                    )

            for max_chars in (199, 20_001):
                with self.subTest(max_chars=max_chars):
                    config = self.make_config(
                        folder,
                        selected_files=("missing.md",),
                        max_chars=max_chars,
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
            with self.assertRaises(ValueError):
                config.validate()

    def test_validate_rejects_selected_file_resolving_outside_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "docs")
            outside = Path(tmp, "docs-escape")
            root.mkdir()
            outside.mkdir()
            Path(root, "document.md").write_text("inside", encoding="utf-8")
            escaped = Path(outside, "document.md").resolve()
            real_resolve = Path.resolve

            def fake_resolve(path, *args, **kwargs):
                if path.parent == root and path.name == "document.md":
                    return escaped
                return real_resolve(path, *args, **kwargs)

            config = self.make_config(root)
            with patch.object(Path, "resolve", fake_resolve):
                with self.assertRaisesRegex(ValueError, "文档目录"):
                    config.validate()


    def test_llm_thinking_is_disabled_by_default_and_snapshotted(self):
        llm = run_config.LLMConfig(
            provider_id="deepseek",
            api_key="secret",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
        )
        self.assertFalse(llm.enable_thinking)
        self.assertFalse(llm.sanitized()["enable_thinking"])

    def test_from_settings_reads_explicit_thinking_true(self):
        with mock.patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "ollama",
                "LLM_ENABLE_THINKING": "YES",
            },
            clear=False,
        ):
            config = run_config.PipelineConfig.from_settings()
        self.assertTrue(config.llm.enable_thinking)

    def test_from_settings_defaults_thinking_to_false(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch.dict(
                os.environ, {"LLM_ENABLE_THINKING": ""}, clear=False
            ):
                config = run_config.PipelineConfig.from_settings()
        self.assertFalse(config.llm.enable_thinking)

    def test_thinking_only_model_requires_explicit_enable(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "document.md").write_text(
                "content", encoding="utf-8"
            )
            config = self.make_config(folder)
            config = replace(
                config,
                llm=replace(
                    config.llm,
                    model="deepseek-reasoner",
                    enable_thinking=False,
                ),
            )
            with self.assertRaisesRegex(ValueError, "仅思考模型"):
                config.validate()
            replace(
                config,
                llm=replace(config.llm, enable_thinking=True),
            ).validate()


class RunConfigAvailabilityTests(unittest.TestCase):
    def test_run_config_module_exists(self):
        self.assertIsNotNone(run_config, "kg_extract_build.run_config is missing")


if __name__ == "__main__":
    unittest.main()
