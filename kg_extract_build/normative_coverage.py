"""声明规范覆盖状态计算（covered/partial/uncovered/cited_but_unindexed）。"""

from __future__ import annotations


def compute_coverage(candidates_by_family, version_index_map, requested_families, conflicts):
    coverage = []
    for family_id in requested_families:
        candidates = candidates_by_family.get(family_id, [])
        version_ids = [item.version_id for item in candidates]
        indexed = [vid for vid in version_ids if version_index_map.get(vid)]
        if not candidates:
            status = "uncovered"
        elif not indexed:
            status = "cited_but_unindexed"
        elif len(indexed) < len(version_ids):
            status = "partial"
        else:
            status = "covered"
        coverage.append(
            {
                "family_id": family_id,
                "coverage_status": status,
                "candidate_version_ids": version_ids,
                "same_year_version_conflict": bool(conflicts.get(family_id)),
                "warnings": [],
            }
        )
    return coverage
