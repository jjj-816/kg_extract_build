import unittest

from kg_extract_build.audit.normative_scope import NormativeScope, preflight_normative_scope
from kg_extract_build.normative import NormativeVersionCandidate


def version(vid, family="declared", status="published", confirmed=True):
    return NormativeVersionCandidate(vid, family, 2025, None, confirmed, status)


class NormativeScopeTests(unittest.TestCase):
    def test_scope_freezes_declared_and_supplemental_families(self):
        scope = NormativeScope.freeze(2025, ["declared", "declared"], ["required"], ["动火作业", "动火作业"])
        self.assertEqual(scope.family_ids, ("declared", "required"))
        self.assertEqual(scope.work_types, ("动火作业",))

    def test_uncovered_family_blocks_compliance(self):
        scope = NormativeScope.freeze(2025, ["declared"], ["required"])
        result = preflight_normative_scope(scope, {"declared": [version("v1")]}, {"v1": "index"}, {})
        self.assertTrue(result.blocked)
        self.assertFalse(result.can_start_compliance)
        self.assertIn("required", " ".join(result.blocking_reasons))

    def test_conflict_and_unconfirmed_versions_are_visible(self):
        scope = NormativeScope.freeze(2025, ["declared"], [])
        candidates = {"declared": [version("v1"), version("v2", confirmed=False)]}
        result = preflight_normative_scope(scope, candidates, {"v1": "index", "v2": "index"}, {"declared": True})
        self.assertTrue(result.blocked)
        self.assertIn("同年版本冲突", " ".join(result.blocking_reasons))
        self.assertIn("尚未确认适用", " ".join(result.blocking_reasons))
        self.assertEqual(result.display_summary()["审核基准年份"], 2025)


if __name__ == "__main__":
    unittest.main()
