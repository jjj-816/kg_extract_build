import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from kg_extract_build.persistence import MemoryExperimentStore
from kg_extract_build.pipeline import retrieve_entity_evidence, run_pipeline
from kg_extract_build.run_config import LLMConfig, PipelineConfig
from kg_extract_build.vector_store import NullVectorStore


class Schema:
    schema_path = Path("schema.json")
    entity_types = {}
    relation_types = {}

    def normalize_entity_type(self, value):
        return value

    def render_entity_schema(self):
        return "设施"

    def is_relation_allowed(self, *args):
        return True


class TimelineRetriever:
    sentences = ["共同证据", "C 独立证据"]
    sent_embeddings = []
    top_n = 10
    timeline = None

    def __init__(self, *args, **kwargs):
        pass

    def export_segments(self):
        return [
            {"index": 0, "content": "共同证据"},
            {"index": 1, "content": "C 独立证据"},
        ]

    def retrieve_with_details(self, name):
        self.timeline.append(f"retrieve:{name}")
        if name in {"A", "B"}:
            return [
                {
                    "sentence_index": 0,
                    "sentence": "共同证据",
                    "score": 1.0,
                    "match_type": "direct",
                }
            ]
        return [
            {
                "sentence_index": 1,
                "sentence": "C 独立证据",
                "score": 1.0,
                "match_type": "direct",
            }
        ]


class PipelineRelationBatchingTests(unittest.TestCase):
    def test_retrieval_keeps_direct_and_high_score_hits_before_source_order(self):
        class Retriever:
            top_n = 2

            def retrieve_with_details(self, alias):
                return [
                    {
                        "sentence_index": 1,
                        "sentence": "低分语义证据",
                        "score": 0.61,
                        "match_type": "semantic",
                    },
                    {
                        "sentence_index": 10,
                        "sentence": "直接命中证据",
                        "score": 1.0,
                        "match_type": "direct",
                    },
                    {
                        "sentence_index": 5,
                        "sentence": "高分语义证据",
                        "score": 0.95,
                        "match_type": "semantic",
                    },
                ]

        evidence = retrieve_entity_evidence(
            Retriever(),
            {"name": "井口", "aliases": ["井口"]},
        )

        self.assertEqual(
            [item["sentence_index"] for item in evidence],
            [5, 10],
        )

    def test_pipeline_retrieves_all_entities_before_grouped_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("共同证据。C 独立证据。", encoding="utf-8")
            config = PipelineConfig(
                run_name="批量关系测试",
                document_folder=root,
                selected_files=("a.md",),
                llm=LLMConfig(
                    "ollama",
                    "ollama",
                    "http://localhost:11434/v1/",
                    "qwen3",
                ),
            )
            timeline = []
            TimelineRetriever.timeline = timeline
            extractor = Mock()
            extractor.extract.return_value = [
                {"name": name, "type": "设施"}
                for name in ("A", "B", "C")
            ]
            aligner = Mock()
            aligner.align.return_value = (
                [
                    {
                        "name": name,
                        "type": "设施",
                        "aliases": [name],
                    }
                    for name in ("A", "B", "C")
                ],
                {},
            )
            generator = Mock()
            generator.debug_dir = root

            def generate_batch(entities, **kwargs):
                names = tuple(item["name"] for item in entities)
                timeline.append(f"batch:{','.join(names)}")
                return {name: [] for name in names}

            def generate(entity, context):
                timeline.append(f"single:{entity['name']}")
                return []

            generator.generate_batch.side_effect = generate_batch
            generator.generate.side_effect = generate

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
                    TimelineRetriever,
                ),
                patch(
                    "kg_extract_build.pipeline.TripletGenerator",
                    return_value=generator,
                ),
                patch(
                    "kg_extract_build.pipeline.save_raw_entities",
                    return_value=root / "raw.json",
                ),
                patch(
                    "kg_extract_build.pipeline.save_aligned_entities",
                    return_value=root / "aligned.json",
                ),
                patch(
                    "kg_extract_build.pipeline.current_code_commit",
                    return_value="commit",
                ),
            ):
                run_pipeline(config)

        first_generate = min(
            index
            for index, item in enumerate(timeline)
            if item.startswith(("batch:", "single:"))
        )
        last_retrieve = max(
            index
            for index, item in enumerate(timeline)
            if item.startswith("retrieve:")
        )
        self.assertGreater(first_generate, last_retrieve)
        self.assertIn("batch:A,B", timeline)
        self.assertIn("single:C", timeline)
        self.assertEqual(generator.generate_batch.call_count, 1)
        self.assertEqual(generator.generate.call_count, 1)


if __name__ == "__main__":
    unittest.main()
