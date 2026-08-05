import unittest

from kg_extract_build.normative import NormativeVersionCandidate
from kg_extract_build.normative_coverage import compute_coverage


def v(vid, family, year=2020, invalid=None, confirmed=True, status="effective"):
    return NormativeVersionCandidate(vid, family, year, invalid, confirmed, status)


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.families = {
            "f1": [v("v1", "f1"), v("v2", "f1", 2025)],
            "f2": [v("v3", "f2")],
        }

    def test_covered_when_all_candidates_indexed(self):
        result = compute_coverage(self.families, {"v1": "i1", "v2": "i2"}, ["f1"], {})
        self.assertEqual(result[0]["coverage_status"], "covered")
        self.assertEqual(result[0]["candidate_version_ids"], ["v1", "v2"])

    def test_partial_when_some_indexed(self):
        result = compute_coverage(self.families, {"v1": "i1"}, ["f1"], {})
        self.assertEqual(result[0]["coverage_status"], "partial")

    def test_cited_but_unindexed_when_none_indexed(self):
        result = compute_coverage(self.families, {}, ["f1"], {})
        self.assertEqual(result[0]["coverage_status"], "cited_but_unindexed")

    def test_uncovered_when_no_candidate(self):
        result = compute_coverage({"f3": []}, {}, ["f3"], {})
        self.assertEqual(result[0]["coverage_status"], "uncovered")

    def test_conflict_flag_propagates(self):
        result = compute_coverage(self.families, {"v1": "i1", "v2": "i2"}, ["f1"], {"f1": True})
        self.assertTrue(result[0]["same_year_version_conflict"])
