import unittest

from kg_extract_build.normative_meta import (
    VERSION_STATUSES,
    VersionDraft,
    build_metadata_hash,
    detect_supersede_cycle,
    validate_version_draft,
)


def draft(**overrides):
    base = dict(
        family_id="family-1",
        document_id=36,
        display_name="Q/SY 2000-2020 有限空间作业",
        standard_code="Q/SY 2000-2020",
        version_year=2020,
        effective_year=2020,
        invalid_year=None,
        status="effective",
        supersedes_version_id=None,
        metadata_confirmed=False,
    )
    base.update(overrides)
    return VersionDraft(**base)


class NormativeMetaTests(unittest.TestCase):
    def test_statuses_contain_design_values(self):
        self.assertEqual(
            VERSION_STATUSES,
            {"pending_confirmation", "effective", "superseded", "repealed", "unknown"},
        )

    def test_effective_after_invalid_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "生效年份不能晚于失效年份"):
            validate_version_draft(draft(effective_year=2021, invalid_year=2020), [])

    def test_superseded_without_invalid_year_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "必须确认 invalid_year"):
            validate_version_draft(draft(status="superseded", invalid_year=None), [])

    def test_valid_draft_passes(self):
        validate_version_draft(draft(), [])

    def test_supersede_cycle_is_detected(self):
        a = draft(version_id="v1", supersedes_version_id="v2")
        b = draft(version_id="v2", family_id="family-1", document_id=37, display_name="新版",
                  standard_code="Q/SY 2000-2025", version_year=2025, effective_year=2025,
                  supersedes_version_id="v1")
        self.assertTrue(detect_supersede_cycle("v1", [a, b]))
        with self.assertRaisesRegex(ValueError, "循环"):
            validate_version_draft(draft(supersedes_version_id="v1"), [a, b])

    def test_metadata_hash_is_stable_and_sensitive(self):
        base = draft()
        self.assertEqual(build_metadata_hash(base), build_metadata_hash(base))
        changed = draft(display_name="其他名称")
        self.assertNotEqual(build_metadata_hash(base), build_metadata_hash(changed))
