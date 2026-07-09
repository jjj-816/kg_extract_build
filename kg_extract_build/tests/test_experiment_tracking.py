import os
import sys
import unittest
from pathlib import Path


TEST_PARENT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = TEST_PARENT.parent if TEST_PARENT.name == "kg_extract_build" else TEST_PARENT
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from kg_extract_build.persistence import ExperimentRecorder, MemoryExperimentStore


class FakeVectorStore:
    enabled = True

    def __init__(self):
        self.calls = []

    def upsert_segments(self, records, embeddings):
        self.calls.append((records, embeddings))

    def close(self):
        return None


class ExperimentRecorderTests(unittest.TestCase):
    def test_records_chunks_and_vectors_with_stable_ids(self):
        store = MemoryExperimentStore()
        vector_store = FakeVectorStore()
        run_id = store.start_run("test", {}, {}, "commit")
        document_id = store.start_document(run_id, "doc.md", "spec", "abc", "text")
        recorder = ExperimentRecorder(store, vector_store, run_id, document_id)

        ids = recorder.record_chunks(
            "retrieval_sentence",
            [
                {"index": 0, "content": "第一句", "start_offset": 0, "end_offset": 3},
                {"index": 1, "content": "第二句", "start_offset": 4, "end_offset": 7},
            ],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
        )

        self.assertEqual(len(ids), 2)
        self.assertEqual(recorder.chunk_id("retrieval_sentence", 1), ids[1])
        self.assertEqual(vector_store.calls[0][0][0]["chunk_id"], ids[0])

    def test_records_llm_entities_retrieval_and_triplets(self):
        store = MemoryExperimentStore()
        run_id = store.start_run("test", {}, {}, "")
        document_id = store.start_document(run_id, "doc.md", "case", "abc", "text")
        recorder = ExperimentRecorder(store, FakeVectorStore(), run_id, document_id)
        recorder.record_chunks(
            "retrieval_sentence",
            [{"index": 0, "content": "井口需要检测。"}],
        )

        call_id = recorder.record_llm_call(
            stage="entity_extraction",
            prompt="prompt",
            raw_response='[{"name":"井口"}]',
            parsed=[{"name": "井口"}],
            latency_ms=12,
        )
        recorder.record_entities("raw", [{"name": "井口", "type": "设施"}])
        recorder.record_retrieval(
            "井口",
            "井口",
            [{"sentence_index": 0, "sentence": "井口需要检测", "score": 1.0, "match_type": "direct"}],
        )
        recorder.record_triplets(
            "final",
            [("井口", "设施", "需要", "检测", "作业")],
            source_llm_call_id=call_id,
        )

        self.assertEqual(len(store.llm_calls), 1)
        self.assertEqual(len(store.entities), 1)
        self.assertEqual(store.retrieval_results[0]["chunk_id"], recorder.chunk_id("retrieval_sentence", 0))
        self.assertEqual(store.triplets[0]["head"], "井口")

    def test_reports_each_persisted_llm_call_to_callback(self):
        store = MemoryExperimentStore()
        run_id = store.start_run("test", {}, {}, "")
        document_id = store.start_document(
            run_id, "doc.md", "case", "abc", "text"
        )
        callbacks = []
        recorder = ExperimentRecorder(
            store,
            FakeVectorStore(),
            run_id,
            document_id,
            model_name="model",
            event_callback=callbacks.append,
        )
        recorder.record_llm_call(
            stage="entity_extraction", prompt="prompt"
        )
        self.assertEqual(
            callbacks, [{"stage": "entity_extraction", "success": True}]
        )


if __name__ == "__main__":
    unittest.main()


class EvaluationPersistenceTests(unittest.TestCase):
    def test_memory_store_saves_and_lists_evaluations(self):
        from kg_extract_build.evaluation import EvaluationResult, MetricValue

        store = MemoryExperimentStore()
        run_id = store.start_run("评估测试", {}, {}, "")
        result = EvaluationResult(
            overall={"triplet_f1": MetricValue("triplet_f1", 0.75)},
            by_document={},
            matched_documents=["doc"],
            missing_gold_documents=[],
            extra_gold_documents=[],
        )

        evaluation_id = store.save_evaluation(
            run_id=run_id,
            gold_path="D:/gold",
            gold_hash="a" * 64,
            metric_config={"matching": "strict"},
            result=result,
        )
        rows = store.list_evaluations(run_id, gold_hash="a" * 64)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evaluation_id"], evaluation_id)
        self.assertEqual(rows[0]["triplet_f1"], 0.75)
