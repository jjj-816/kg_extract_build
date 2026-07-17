import unittest

from kg_extract_build.persistence import MemoryExperimentStore


class BatchDeletionTests(unittest.TestCase):
    def test_memory_store_deletes_only_selected_run_and_children(self):
        store = MemoryExperimentStore()
        delete_run_id = store.start_run("delete", {}, {}, "")
        keep_run_id = store.start_run("keep", {}, {}, "")
        delete_doc = store.start_document(delete_run_id, "delete.md", "case", "a", "text")
        keep_doc = store.start_document(keep_run_id, "keep.md", "case", "b", "text")
        store.save_chunks(delete_run_id, delete_doc, "retrieval_sentence", [{"index": 0, "content": "delete"}])
        store.save_chunks(keep_run_id, keep_doc, "retrieval_sentence", [{"index": 0, "content": "keep"}])

        self.assertTrue(store.delete_run(delete_run_id))
        self.assertNotIn(delete_run_id, store.runs)
        self.assertIn(keep_run_id, store.runs)
        self.assertEqual([row["run_id"] for row in store.chunks], [keep_run_id])
        self.assertFalse(store.delete_run(delete_run_id))


if __name__ == "__main__":
    unittest.main()
