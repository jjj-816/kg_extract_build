import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kg_extract_build.entity_aligner import EntityAligner
from kg_extract_build.extractor import LongDocLLMEntityExtractor
from kg_extract_build.persistence import MemoryExperimentStore
from kg_extract_build.pipeline import run_pipeline
from kg_extract_build.run_config import ChunkingConfig, LLMConfig, PipelineConfig
from kg_extract_build.runtime import CancellationToken, PipelineCancelled, PipelineEvent
from kg_extract_build.vector_store import NullVectorStore


class Schema:
    schema_path = Path("schema.json")
    entity_types = {}
    relation_types = {}

    def normalize_entity_type(self, value):
        return value

    def render_entity_schema(self):
        return "设施"


class PipelineControlTests(unittest.TestCase):
    def test_extractor_stops_before_first_chunk_request(self):
        token = CancellationToken()
        token.cancel()
        extractor = LongDocLLMEntityExtractor.__new__(LongDocLLMEntityExtractor)
        extractor.max_chunk_size = 2000
        extractor.expert_entities = []
        extractor.schema = Schema()
        with self.assertRaises(PipelineCancelled):
            extractor.extract("# 标题\n内容", cancel_token=token)

    def test_aligner_stops_between_candidate_groups(self):
        token = CancellationToken()
        token.cancel()
        aligner = EntityAligner.__new__(EntityAligner)
        aligner._deduplicate_entities = lambda entities, source_type: entities
        aligner._build_candidate_groups = lambda entities: [
            [entities[0], entities[1]]
        ]
        with self.assertRaises(PipelineCancelled):
            aligner.align(
                [
                    {"name": "井口", "type": "设施"},
                    {"name": "井口装置", "type": "设施"},
                ],
                cancel_token=token,
            )

    def test_pipeline_event_never_contains_api_key(self):
        event = PipelineEvent("started", "run", "开始")
        self.assertNotIn("api_key", event.__dict__)

    def test_extractor_redacts_secret_from_recorded_error(self):
        class FailingCompletions:
            def create(self, **kwargs):
                raise RuntimeError("Authorization: Bearer top-secret")

        class Recorder:
            def __init__(self):
                self.error_message = ""

            def record_llm_call(self, **kwargs):
                self.error_message = kwargs["error_message"]

        extractor = LongDocLLMEntityExtractor.__new__(LongDocLLMEntityExtractor)
        extractor.client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": FailingCompletions()})()},
        )()
        extractor.model = "model"
        extractor.schema = Schema()
        extractor._secret_values = ("top-secret",)
        recorder = Recorder()
        extractor._extract_from_chunk("内容", recorder=recorder, chunk_index=0)
        self.assertNotIn("top-secret", recorder.error_message)

    def test_cancelled_pipeline_persists_cancelled_status_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("# 标题\n内容", encoding="utf-8")
            config = PipelineConfig(
                run_name="取消测试",
                document_folder=root,
                selected_files=("a.md",),
                llm=LLMConfig(
                    "ollama",
                    "ollama",
                    "http://localhost:11434/v1/",
                    "qwen3",
                ),
                chunking=ChunkingConfig(),
            )
            store = MemoryExperimentStore()
            token = CancellationToken()
            token.cancel()
            events = []
            with (
                patch(
                    "kg_extract_build.pipeline.KGSchema", return_value=Schema()
                ),
                patch(
                    "kg_extract_build.pipeline.build_experiment_store",
                    return_value=store,
                ),
                patch(
                    "kg_extract_build.pipeline.build_vector_store",
                    return_value=NullVectorStore(),
                ),
                patch(
                    "kg_extract_build.pipeline.current_code_commit",
                    return_value="commit",
                ),
                patch("kg_extract_build.extractor.OpenAI"),
                patch("kg_extract_build.entity_aligner.OpenAI"),
            ):
                run_id = run_pipeline(config, events.append, token)

        self.assertEqual(store.runs[run_id]["status"], "cancelled")
        self.assertEqual(
            [event.event_type for event in events],
            ["started", "cancelled"],
        )
        snapshot_str = repr(store.runs[run_id]["config_snapshot"])
        self.assertNotIn("api_key:", snapshot_str)
        self.assertNotIn("ollama\"", snapshot_str)


if __name__ == "__main__":
    unittest.main()
