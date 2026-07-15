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

    def test_evaluation_input_only_attaches_retrieval_for_triplet_head(self):
        store = MemoryExperimentStore()
        run_id = store.start_run("test", {}, {}, "")
        document_id = store.start_document(run_id, "doc.md", "case", "abc", "A B")
        store.save_triplets([
            {
                "run_id": run_id,
                "document_id": document_id,
                "stage": "final",
                "head": "A",
                "head_type": "类型1",
                "relation": "REL",
                "tail": "B",
                "tail_type": "类型2",
            }
        ])
        store.save_retrieval_results([
            {
                "run_id": run_id,
                "document_id": document_id,
                "entity_name": "A",
                "query_alias": "A",
                "sentence": "A 的检索句",
            },
            {
                "run_id": run_id,
                "document_id": document_id,
                "entity_name": "B",
                "query_alias": "B",
                "sentence": "B 的检索句",
            },
        ])

        store.save_triplet_evidence(1, [1])
        evidence = store.load_evaluation_input(run_id)["evidence"]
        triplet = ("A", "类型1", "REL", "B", "类型2")
        self.assertEqual(evidence["doc"][triplet], ["A 的检索句"])

    def test_final_triplet_links_selected_retrieval_sentence(self):
        store = MemoryExperimentStore()
        run_id = store.start_run("test", {}, {}, "")
        document_id = store.start_document(run_id, "doc.md", "case", "abc", "text")
        recorder = ExperimentRecorder(store, None, run_id, document_id)
        recorder.record_chunks(
            "retrieval_sentence", [{"index": 4, "content": "A REL B"}]
        )
        recorder.record_retrieval(
            "A", "A", [{"sentence_index": 4, "sentence": "A REL B", "score": 1.0, "match_type": "direct"}]
        )
        recorder.record_triplets("final", [{
            "head": "A", "head_type": "T", "relation": "REL", "tail": "B",
            "tail_type": "T", "evidence_sentence_ids": [4],
        }])

        self.assertEqual(len(store.triplet_evidence), 1)
        self.assertEqual(store.triplet_evidence[0]["evidence_order"], 1)

    def test_memory_store_deletes_only_selected_run_and_children(self):
        store = MemoryExperimentStore()
        deleted_run_id = store.start_run("delete", {}, {}, "")
        retained_run_id = store.start_run("retain", {}, {}, "")
        deleted_document_id = store.start_document(
            deleted_run_id, "delete.md", "case", "deleted", "delete text"
        )
        retained_document_id = store.start_document(
            retained_run_id, "retain.md", "case", "retained", "retain text"
        )
        store.save_chunks(
            deleted_run_id,
            deleted_document_id,
            "retrieval_sentence",
            [{"index": 0, "content": "delete"}],
        )
        store.save_chunks(
            retained_run_id,
            retained_document_id,
            "retrieval_sentence",
            [{"index": 0, "content": "retain"}],
        )

        self.assertTrue(store.delete_run(deleted_run_id))
        self.assertNotIn(deleted_run_id, store.runs)
        self.assertNotIn(deleted_document_id, store.documents)
        self.assertFalse(any(row["run_id"] == deleted_run_id for row in store.chunks))
        self.assertIn(retained_run_id, store.runs)
        self.assertIn(retained_document_id, store.documents)
        self.assertTrue(any(row["run_id"] == retained_run_id for row in store.chunks))
        self.assertFalse(store.delete_run(deleted_run_id))

    def test_memory_store_deletes_evaluation_metrics_for_selected_run(self):
        store = MemoryExperimentStore()
        deleted_run_id = store.start_run("delete", {}, {}, "")
        retained_run_id = store.start_run("retain", {}, {}, "")
        store.evaluation_runs = [
            {"evaluation_id": "delete-evaluation", "run_id": deleted_run_id},
            {"evaluation_id": "retain-evaluation", "run_id": retained_run_id},
        ]
        store.evaluation_metrics = [
            {"evaluation_id": "delete-evaluation"},
            {"evaluation_id": "retain-evaluation"},
        ]

        store.delete_run(deleted_run_id)

        self.assertEqual(
            store.evaluation_metrics,
            [{"evaluation_id": "retain-evaluation"}],
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
