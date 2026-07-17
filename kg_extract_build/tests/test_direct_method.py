import unittest

from kg_extract_build.method_profiles import get_method_profile
from kg_extract_build.pipeline import get_run_debug_dir


class DirectMethodProfileTests(unittest.TestCase):
    def test_r2_description_states_chunked_direct_extraction(self):
        profile = get_method_profile("R2")
        self.assertIn("切片", profile.description)
        self.assertEqual(profile.relation_strategy, "llm_direct")

    def test_debug_paths_are_isolated_by_run_id(self):
        self.assertNotEqual(
            get_run_debug_dir("debug", "run-a"),
            get_run_debug_dir("debug", "run-b"),
        )
        self.assertEqual(str(get_run_debug_dir("debug", "run-a")), "debug\\run-a")


if __name__ == "__main__":
    unittest.main()
