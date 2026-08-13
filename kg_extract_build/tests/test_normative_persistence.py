import re
import unittest
from collections import defaultdict

from kg_extract_build.normative import ClauseDraft, NormativeVersionCandidate
from kg_extract_build.normative_meta import FamilyDraft, VersionDraft
from kg_extract_build.normative_persistence import NormativeStore


class InMemoryBackend:
    """记录 INSERT/UPDATE 到内存表，按 SELECT 表名回放缓存行。"""

    def __init__(self):
        self.rows: dict[str, list[dict]] = defaultdict(list)
        self.statements: list[str] = []
        self._auto = 1

    def _write(self, sql, params=None, many=False):
        self.statements.append(sql)
        table = re.search(r"(?:INSERT INTO|UPDATE)\s+(\w+)", sql).group(1)
        if not sql.strip().upper().startswith("INSERT"):
            return 1
        rows = [tuple(params or ())] if not many else [tuple(p) for p in (params or [])]
        cols = [c.strip().strip("`") for c in re.search(r"\(([^)]+)\)", sql).group(1).split(",")]
        last = None
        for values in rows:
            row = dict(zip(cols, values))
            pk = [c for c in cols if c in {"version_id", "clause_set_id", "index_id"}]
            key = row.get(pk[0], self._auto) if pk else self._auto
            if not pk:
                row["id"] = self._auto
                self._auto += 1
            if many:
                self.rows[table].append(row)
            else:
                existing = [r for r in self.rows[table] if r.get(pk[0]) == key] if pk else []
                if existing:
                    existing[0].update(row)
                else:
                    self.rows[table].append(row)
            last = key
        return last

    def _read(self, sql, params=None):
        table = re.search(r"FROM\s+(\w+)", sql).group(1)
        rows = [dict(r) for r in self.rows[table]]
        where = re.search(r"WHERE\s+(.+?)(?:\s+(?:LIMIT|ORDER|GROUP)\b|$)", sql, re.IGNORECASE)
        if where:
            m = re.match(r"(\w+)\s*=\s*%s", where.group(1).strip())
            if m:
                col = m.group(1)
                value = (params or ())[0]
                rows = [r for r in rows if r.get(col) == value]
        return rows


class NormativePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.backend = InMemoryBackend()
        self.store = NormativeStore(self.backend)

    def test_save_family_and_version_roundtrip(self):
        self.store.save_family("family-1", FamilyDraft("有限空间作业安全规程", "Q/SY 2000"))
        version_id = self.store.save_version(
            VersionDraft(
                family_id="family-1", document_id=36, display_name="Q/SY 2000-2020",
                effective_year=2020, status="effective", metadata_confirmed=True,
            )
        )
        row = self.store.get_version(version_id)
        self.assertEqual(row["family_id"], "family-1")
        self.assertEqual(row["effective_year"], 2020)

    def test_save_clause_set_and_clauses(self):
        self.store.save_clause_set("set-1", "version-1", 36, "hash-src", "normative-clause-v1", "cfg", "published")
        self.store.save_clauses(
            "set-1", "version-1", 36,
            [ClauseDraft("第二十条", ("总则",), None, "作业前应通风。", "作业前应通风。", 0, 8, "structured")],
        )
        rows = self.store.get_clauses("set-1")
        self.assertEqual(rows[0]["clause_number"], "第二十条")
        self.assertEqual(rows[0]["raw_text"], "作业前应通风。")

    def test_has_normative_references_true_when_version_exists(self):
        self.store.save_family("family-1", FamilyDraft("有限空间作业安全规程", "Q/SY 2000"))
        self.store.save_version(
            VersionDraft(family_id="family-1", document_id=36, display_name="v",
                         effective_year=2020, status="effective")
        )
        self.assertTrue(self.store.has_normative_references(36))

    def test_version_candidates_include_only_metadata_confirmed(self):
        self.store.save_family("family-1", FamilyDraft("有限空间作业安全规程", "Q/SY 2000"))
        self.store.save_version(
            VersionDraft(family_id="family-1", document_id=36, display_name="v",
                         effective_year=2020, status="effective", metadata_confirmed=True)
        )
        self.store.save_version(
            VersionDraft(family_id="family-1", document_id=37, display_name="u",
                         effective_year=2020, status="pending_confirmation", metadata_confirmed=False)
        )
        candidates = self.store.version_candidates()
        self.assertEqual([c.metadata_confirmed for c in candidates], [True])

    def test_asset_overview_flags_version_name_not_matching_family(self):
        class AssetOverviewBackend(InMemoryBackend):
            def _read(self, sql, params=None):
                if "FROM kg_normative_family f" in sql:
                    return [{
                        "family_id": "family-shale-gas",
                        "canonical_name": "页岩气地面工程设计规范",
                        "standard_code_base": "Q/SY1858",
                        "version_id": "version-confined-space",
                        "display_name": "有限空间作业安全规范 2020",
                        "standard_code": "GB 30871-2022",
                    }]
                return super()._read(sql, params)

        rows = NormativeStore(AssetOverviewBackend()).asset_overview()

        self.assertEqual(rows[0]["family_consistency"], "mismatch")
        self.assertFalse(rows[0]["eligible_for_supersession"])

    def test_asset_overview_flags_name_mismatch_even_when_standard_code_matches(self):
        class AssetOverviewBackend(InMemoryBackend):
            def _read(self, sql, params=None):
                if "FROM kg_normative_family f" in sql:
                    return [{
                        "family_id": "family-shale-gas",
                        "canonical_name": "页岩气地面工程设计规范",
                        "standard_code_base": "Q/SY1858",
                        "version_id": "version-confined-space",
                        "display_name": "有限空间作业安全规范 2020",
                        "standard_code": "Q/SY1858-2015",
                    }]
                return super()._read(sql, params)

        rows = NormativeStore(AssetOverviewBackend()).asset_overview()

        self.assertEqual(rows[0]["family_consistency"], "mismatch")

    def test_version_candidates_exclude_confirmed_mismatched_family_asset(self):
        self.store.save_family("family-shale-gas", FamilyDraft("页岩气地面工程设计规范", "Q/SY1858"))
        self.store.save_version(
            VersionDraft(
                family_id="family-shale-gas", document_id=36,
                display_name="有限空间作业安全规范 2020", standard_code="GB 30871-2022",
                effective_year=2020, status="effective", metadata_confirmed=True,
            )
        )

        candidates = self.store.version_candidates()

        self.assertEqual(candidates, [])

    def test_enabled_indexes_exclude_mismatched_family_asset(self):
        class EnabledIndexBackend(InMemoryBackend):
            def _read(self, sql, params=None):
                if "FROM kg_normative_index" in sql:
                    return [{
                        "index_id": "index-confined-space",
                        "version_id": "version-confined-space",
                        "display_name": "有限空间作业安全规范 2020",
                        "standard_code": "GB 30871-2022",
                        "canonical_name": "页岩气地面工程设计规范",
                        "standard_code_base": "Q/SY1858",
                    }]
                return super()._read(sql, params)

        indexes = NormativeStore(EnabledIndexBackend()).list_audit_enabled_indexes()

        self.assertEqual(indexes, [])
