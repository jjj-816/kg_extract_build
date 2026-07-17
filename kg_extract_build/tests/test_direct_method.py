import unittest

from kg_extract_build.method_profiles import get_method_profile


class DirectMethodProfileTests(unittest.TestCase):
    def test_r2_description_states_chunked_direct_extraction(self):
        profile = get_method_profile("R2")
        self.assertIn("切片", profile.description)
        self.assertEqual(profile.relation_strategy, "llm_direct")


if __name__ == "__main__":
    unittest.main()
