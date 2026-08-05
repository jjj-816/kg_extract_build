import os
import tempfile
import unittest
from pathlib import Path

from kg_extract_build import settings


class NormativeSettingsTests(unittest.TestCase):
    def test_norm_model_path_default(self):
        self.assertEqual(
            settings.NORM_VECTOR_MODEL_PATH,
            settings.VECTOR_MODEL_PATH,
        )

    def test_norm_milvus_defaults(self):
        self.assertEqual(settings.NORM_MILVUS_URI, "http://127.0.0.1:19530")
        self.assertEqual(settings.NORM_MILVUS_COLLECTION_PREFIX, "kg_normative_clauses")
        self.assertFalse(settings.NORM_MILVUS_ENABLED)

    def test_env_override(self):
        with tempfile.TemporaryDirectory() as folder:
            os.environ["KG_NORM_MILVUS_COLLECTION_PREFIX"] = "kg_norm_custom"
            try:
                import importlib
                importlib.reload(settings)
                self.assertEqual(settings.NORM_MILVUS_COLLECTION_PREFIX, "kg_norm_custom")
            finally:
                os.environ.pop("KG_NORM_MILVUS_COLLECTION_PREFIX", None)
                importlib.reload(settings)
