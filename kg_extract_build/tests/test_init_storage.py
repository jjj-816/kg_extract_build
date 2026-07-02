import sys
import unittest
from pathlib import Path


TEST_PARENT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = TEST_PARENT.parent if TEST_PARENT.name == "kg_extract_build" else TEST_PARENT
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from kg_extract_build.init_storage import validate_database_name


class InitStorageTests(unittest.TestCase):
    def test_accepts_safe_database_name(self):
        self.assertEqual(validate_database_name("kg_experiments_2026"), "kg_experiments_2026")

    def test_rejects_sql_fragments(self):
        with self.assertRaises(ValueError):
            validate_database_name("kg;DROP DATABASE mysql")


if __name__ == "__main__":
    unittest.main()
