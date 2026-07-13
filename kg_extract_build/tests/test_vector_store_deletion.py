import inspect
import unittest

from kg_extract_build.vector_store import MilvusSegmentStore, NullVectorStore


class FakeMilvusClient:
    def __init__(self):
        self.calls = []

    def delete(self, collection_name, filter):
        self.calls.append((collection_name, filter))


class VectorStoreDeletionTests(unittest.TestCase):
    def test_delete_methods_expose_run_id_and_none_annotations(self):
        for store_class in (NullVectorStore, MilvusSegmentStore):
            signature = inspect.signature(store_class.delete_segments_by_run)
            self.assertEqual(signature.parameters["run_id"].annotation, str)
            self.assertIsNone(signature.return_annotation)

    def test_null_store_deletes_segments_as_a_no_op(self):
        self.assertIsNone(NullVectorStore().delete_segments_by_run("run-123"))

    def test_milvus_store_deletes_vectors_by_exact_run_id(self):
        store = MilvusSegmentStore.__new__(MilvusSegmentStore)
        store.collection_name = "segments"
        store.client = FakeMilvusClient()

        store.delete_segments_by_run("run-123")

        self.assertEqual(store.client.calls, [("segments", 'run_id == "run-123"')])

    def test_milvus_store_escapes_run_id_for_filter_literal(self):
        store = MilvusSegmentStore.__new__(MilvusSegmentStore)
        store.collection_name = "segments"
        store.client = FakeMilvusClient()

        store.delete_segments_by_run('run\\part"quoted')

        self.assertEqual(
            store.client.calls,
            [("segments", 'run_id == "run\\\\part\\"quoted"')],
        )


if __name__ == "__main__":
    unittest.main()
