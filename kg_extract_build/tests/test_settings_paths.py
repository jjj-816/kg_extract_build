import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TEST_LOCATION = Path(__file__).resolve().parent
PACKAGE_PARENT = (
    TEST_LOCATION.parent if TEST_LOCATION.name == "tests" else TEST_LOCATION
)
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from kg_extract_build.settings import env_path


class SettingsPathTests(unittest.TestCase):
    def test_blank_environment_value_uses_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            default = Path(temp_dir) / "default"
            with patch.dict(os.environ, {"KG_TEST_PATH": ""}):
                self.assertEqual(env_path("KG_TEST_PATH", default), default.resolve())


if __name__ == "__main__":
    unittest.main()
