import tempfile
import unittest
from pathlib import Path

from kg_extract_build.run_config import LLMConfig, PipelineConfig
from kg_extract_build.source_profiles import (
    get_source_prompt_profile,
    resolve_source_type,
)


class SourceProfileTests(unittest.TestCase):
    def test_explicit_choice_wins_over_filename(self):
        self.assertEqual(resolve_source_type("case", "安全规范.md"), "case")
        self.assertEqual(resolve_source_type("spec", "施工方案.md"), "spec")

    def test_auto_uses_legacy_filename_heuristic(self):
        self.assertEqual(resolve_source_type("auto", "安全规范.md"), "spec")
        self.assertEqual(resolve_source_type("auto", "施工方案.md"), "case")

    def test_profiles_are_distinct_and_versioned(self):
        case = get_source_prompt_profile("case")
        spec = get_source_prompt_profile("spec")
        self.assertNotEqual(case.prompt_version, spec.prompt_version)
        self.assertIn("完整条款", spec.triplet_guidance)

    def test_pipeline_snapshot_records_requested_source_type(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "doc.md").write_text("内容", encoding="utf-8")
            config = PipelineConfig(
                run_name="source-test",
                document_folder=Path(folder),
                selected_files=("doc.md",),
                document_source_type="spec",
                llm=LLMConfig(
                    "ollama", "ollama", "http://localhost:11434/v1/", "qwen3"
                ),
            )
            config.validate()
            self.assertEqual(
                config.sanitized_snapshot()["document_source_type_requested"],
                "spec",
            )

    def test_invalid_source_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "doc.md").write_text("内容", encoding="utf-8")
            config = PipelineConfig(
                run_name="source-test",
                document_folder=Path(folder),
                selected_files=("doc.md",),
                document_source_type="other",
                llm=LLMConfig(
                    "ollama", "ollama", "http://localhost:11434/v1/", "qwen3"
                ),
            )
            with self.assertRaisesRegex(ValueError, "来源"):
                config.validate()


if __name__ == "__main__":
    unittest.main()
