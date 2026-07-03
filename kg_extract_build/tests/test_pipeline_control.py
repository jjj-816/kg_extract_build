import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_extractor_raises_when_every_chunk_request_fails(self):
        class FailingCompletions:
            def create(self, **kwargs):
                raise RuntimeError("LLM unavailable")

        extractor = LongDocLLMEntityExtractor.__new__(
            LongDocLLMEntityExtractor
        )
        extractor.client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": FailingCompletions()})()},
        )()
        extractor.model = "model"
        extractor.schema = Schema()
        extractor.max_chunk_size = 2000
        extractor.expert_entities = []
        extractor._secret_values = ()

        with self.assertRaisesRegex(RuntimeError, "全部失败"):
            extractor.extract("内容")

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


    def test_all_documents_failed_sets_failed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("内容", encoding="utf-8")
            config = PipelineConfig(
                run_name="全失败测试",
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
            events = []
            with (
                patch("kg_extract_build.pipeline.KGSchema", return_value=Schema()),
                patch("kg_extract_build.pipeline.build_experiment_store", return_value=store),
                patch("kg_extract_build.pipeline.build_vector_store", return_value=NullVectorStore()),
                patch("kg_extract_build.pipeline.current_code_commit", return_value="commit"),
                patch("kg_extract_build.extractor.OpenAI"),
                patch("kg_extract_build.entity_aligner.OpenAI"),
                patch(
                    "kg_extract_build.extractor.LongDocLLMEntityExtractor.extract",
                    side_effect=RuntimeError("LLM unavailable"),
                ),
            ):
                run_id = run_pipeline(config, events.append)

        self.assertEqual(store.runs[run_id]["status"], "failed")
        terminal = [
            e for e in events if e.event_type in {"failed", "completed_with_errors", "completed"}
        ]
        self.assertEqual(terminal[0].event_type, "failed")
        failed_document = next(
            event for event in events
            if event.event_type == "document_failed"
        )
        self.assertEqual(failed_document.metrics, {"documents": 1})

    def test_vector_store_initialization_failure_closes_store_and_emits_failure(self):
        class TrackingStore(MemoryExperimentStore):
            def __init__(self):
                super().__init__()
                self.closed = False

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("内容", encoding="utf-8")
            config = PipelineConfig(
                run_name="资源释放测试",
                document_folder=root,
                selected_files=("a.md",),
                llm=LLMConfig(
                    "ollama", "ollama",
                    "http://localhost:11434/v1/", "qwen3",
                ),
            )
            store = TrackingStore()
            events = []
            with (
                patch("kg_extract_build.pipeline.KGSchema", return_value=Schema()),
                patch(
                    "kg_extract_build.pipeline.build_experiment_store",
                    return_value=store,
                ),
                patch(
                    "kg_extract_build.pipeline.build_vector_store",
                    side_effect=RuntimeError("milvus init failed"),
                ),
                patch("kg_extract_build.pipeline.LongDocLLMEntityExtractor"),
                patch("kg_extract_build.pipeline.EntityAligner"),
            ):
                run_id = run_pipeline(config, events.append)

        self.assertIsNone(run_id)
        self.assertTrue(store.closed)
        self.assertEqual(events[-1].event_type, "failed")
        self.assertIn("milvus init failed", events[-1].message)

    def test_cancellation_after_retrieval_prevents_triplet_request(self):
        class FakeRetriever:
            sentences = ["内容"]
            sent_embeddings = []
            top_n = 10

            def __init__(self, *args, **kwargs):
                pass

            def export_segments(self):
                return [{"index": 0, "content": "内容"}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("内容", encoding="utf-8")
            config = PipelineConfig(
                run_name="取消窗口测试",
                document_folder=root,
                selected_files=("a.md",),
                llm=LLMConfig(
                    "ollama", "ollama",
                    "http://localhost:11434/v1/", "qwen3",
                ),
            )
            token = CancellationToken()
            store = MemoryExperimentStore()
            events = []
            extractor = Mock()
            extractor.extract.return_value = [
                {"name": "井口", "type": "设施"}
            ]
            aligner = Mock()
            aligner.align.return_value = (
                [{"name": "井口", "type": "设施", "aliases": ["井口"]}],
                {},
            )
            generator = Mock()
            generator.debug_dir = root

            def cancel_after_retrieval(*args, **kwargs):
                token.cancel()
                return "井口相关上下文"

            with (
                patch("kg_extract_build.pipeline.KGSchema", return_value=Schema()),
                patch(
                    "kg_extract_build.pipeline.build_experiment_store",
                    return_value=store,
                ),
                patch(
                    "kg_extract_build.pipeline.build_vector_store",
                    return_value=NullVectorStore(),
                ),
                patch(
                    "kg_extract_build.pipeline.LongDocLLMEntityExtractor",
                    return_value=extractor,
                ),
                patch(
                    "kg_extract_build.pipeline.EntityAligner",
                    return_value=aligner,
                ),
                patch(
                    "kg_extract_build.pipeline.CorpusRetriever",
                    FakeRetriever,
                ),
                patch(
                    "kg_extract_build.pipeline.TripletGenerator",
                    return_value=generator,
                ),
                patch(
                    "kg_extract_build.pipeline.retrieve_entity_context",
                    side_effect=cancel_after_retrieval,
                ),
                patch("kg_extract_build.pipeline.save_raw_entities",
                      return_value=root / "raw.json"),
                patch("kg_extract_build.pipeline.save_aligned_entities",
                      return_value=root / "aligned.json"),
                patch("kg_extract_build.pipeline.current_code_commit",
                      return_value="commit"),
            ):
                run_id = run_pipeline(config, events.append, token)

        generator.generate.assert_not_called()
        self.assertEqual(store.runs[run_id]["status"], "cancelled")
        self.assertEqual(events[-1].event_type, "cancelled")

    def test_empty_document_progress_reports_chunks_and_document_metrics(self):
        class EmptyExtractor:
            def extract(self, content, progress_callback=None, **kwargs):
                progress_callback(1, 1)
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("内容", encoding="utf-8")
            config = PipelineConfig(
                run_name="实时指标测试",
                document_folder=root,
                selected_files=("a.md",),
                llm=LLMConfig(
                    "ollama", "ollama",
                    "http://localhost:11434/v1/", "qwen3",
                ),
            )
            store = MemoryExperimentStore()
            events = []
            with (
                patch("kg_extract_build.pipeline.KGSchema", return_value=Schema()),
                patch(
                    "kg_extract_build.pipeline.build_experiment_store",
                    return_value=store,
                ),
                patch(
                    "kg_extract_build.pipeline.build_vector_store",
                    return_value=NullVectorStore(),
                ),
                patch(
                    "kg_extract_build.pipeline.LongDocLLMEntityExtractor",
                    return_value=EmptyExtractor(),
                ),
                patch("kg_extract_build.pipeline.EntityAligner"),
                patch("kg_extract_build.pipeline.save_raw_entities",
                      return_value=root / "raw.json"),
                patch("kg_extract_build.pipeline.current_code_commit",
                      return_value="commit"),
            ):
                run_pipeline(config, events.append)

        chunk_event = next(
            event for event in events if event.event_type == "chunk_progress"
        )
        document_event = next(
            event for event in events if event.event_type == "document_completed"
        )
        self.assertEqual(chunk_event.metrics, {"chunks": 1})
        self.assertEqual(document_event.metrics, {"documents": 1})

    def test_cancellation_after_last_document_event_prevents_completed_run(self):
        class EmptyExtractor:
            def extract(self, content, **kwargs):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("内容", encoding="utf-8")
            config = PipelineConfig(
                run_name="末尾取消测试",
                document_folder=root,
                selected_files=("a.md",),
                llm=LLMConfig(
                    "ollama", "ollama",
                    "http://localhost:11434/v1/", "qwen3",
                ),
            )
            token = CancellationToken()
            store = MemoryExperimentStore()
            events = []

            def capture_and_cancel(event):
                events.append(event)
                if event.event_type == "document_completed":
                    token.cancel()

            with (
                patch("kg_extract_build.pipeline.KGSchema", return_value=Schema()),
                patch(
                    "kg_extract_build.pipeline.build_experiment_store",
                    return_value=store,
                ),
                patch(
                    "kg_extract_build.pipeline.build_vector_store",
                    return_value=NullVectorStore(),
                ),
                patch(
                    "kg_extract_build.pipeline.LongDocLLMEntityExtractor",
                    return_value=EmptyExtractor(),
                ),
                patch("kg_extract_build.pipeline.EntityAligner"),
                patch("kg_extract_build.pipeline.save_raw_entities",
                      return_value=root / "raw.json"),
                patch("kg_extract_build.pipeline.current_code_commit",
                      return_value="commit"),
            ):
                run_id = run_pipeline(config, capture_and_cancel, token)

        self.assertEqual(store.runs[run_id]["status"], "cancelled")
        self.assertEqual(events[-1].event_type, "cancelled")

    def test_cached_entities_publish_live_entity_metric(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("内容", encoding="utf-8")
            config = PipelineConfig(
                run_name="缓存指标测试",
                document_folder=root,
                selected_files=("a.md",),
                llm=LLMConfig(
                    "ollama", "ollama",
                    "http://localhost:11434/v1/", "qwen3",
                ),
                reuse_entity_cache=True,
            )
            events = []
            with (
                patch("kg_extract_build.pipeline.KGSchema", return_value=Schema()),
                patch(
                    "kg_extract_build.pipeline.build_experiment_store",
                    return_value=MemoryExperimentStore(),
                ),
                patch(
                    "kg_extract_build.pipeline.build_vector_store",
                    return_value=NullVectorStore(),
                ),
                patch("kg_extract_build.pipeline.LongDocLLMEntityExtractor"),
                patch("kg_extract_build.pipeline.EntityAligner"),
                patch(
                    "kg_extract_build.pipeline.load_aligned_entities",
                    return_value=[
                        {"name": "井口", "type": "设施", "aliases": ["井口"]}
                    ],
                ),
                patch(
                    "kg_extract_build.pipeline.CorpusRetriever",
                    side_effect=RuntimeError("stop after metric"),
                ),
                patch("kg_extract_build.pipeline.current_code_commit",
                      return_value="commit"),
            ):
                run_pipeline(config, events.append)

        entity_event = next(
            event for event in events if event.event_type == "entities_aligned"
        )
        self.assertEqual(entity_event.metrics, {"entities": 1})


if __name__ == "__main__":
    unittest.main()
