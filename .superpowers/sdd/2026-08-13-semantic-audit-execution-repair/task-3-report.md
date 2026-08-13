# Task 3 report: explain and continue normative candidate filtering

## Scope completed

- Kept applicability preflight advisory and ensured normative retrieval proceeds even when declared-norm coverage is unavailable.
- Added terminal, per-candidate normative evidence filtering with trace fields for declaration match, version validity, substitute-chain validity, clause completeness, applicability, selection, and filter reason.
- Kept the enabled unified normative corpus as the recall source; declaration matching now happens only after retrieval.
- Added a `declared_norm_omission` warning for recalled, otherwise viable clauses that are not declared. These clauses do not enter the compliance conclusion evidence package.

## TDD evidence

- RED: `test_candidate_trace_explains_declared_norm_filtering` first failed because the retrieval trace had no `candidates` field.
- GREEN: the Task 3 compliance-runtime suite passed after the filtering trace and warnings were implemented.

## Verification

```text
$env:PYTHONPATH='.'; $env:PYTHONIOENCODING='utf-8'; conda run -n env_agent python -m pytest kg_extract_build/tests/test_compliance_runtime.py kg_extract_build/tests/test_compliance_planner_integration.py kg_extract_build/tests/test_normative_scope.py kg_extract_build/tests/test_normative_production.py kg_extract_build/tests/test_normative_search.py -q
14 passed in 0.91s

$env:PYTHONPATH='.'; $env:PYTHONIOENCODING='utf-8'; conda run -n env_agent python -m pytest kg_extract_build/tests -q
352 passed, 1 skipped, 51 subtests passed in 5.19s
```

## Notes

- `normative_scope.py` already implemented the required non-blocking advisory preflight before this task began, so it required no source edit.
- No Task 4 files were changed.

## Review follow-up: normative eligibility contract

- Tightened terminal candidate eligibility to require `metadata_confirmed is True`, `version_status == "effective"`, `index_status == "ready"`, no `audit_disabled_at`, and an audit-year-valid effective/invalid date range. Publication/release status is no longer accepted as a substitute for effective version status.
- Added contract coverage rejecting `published` status, absent or false metadata confirmation, non-ready indexes, disabled indexes, future-effective versions, and expired versions.
- Propagated version and index eligibility metadata from the unified-corpus search result so the terminal filter can apply the same contract in production instead of silently rejecting every candidate.
- Updated semantic-compliance fixtures to model the production candidate contract explicitly.

```text
$env:PYTHONPATH='.'; $env:PYTHONIOENCODING='utf-8'; conda run -n env_agent python -m pytest kg_extract_build/tests/test_semantic_compliance.py kg_extract_build/tests/test_normative_search.py kg_extract_build/tests/test_compliance_runtime.py kg_extract_build/tests/test_compliance_planner_integration.py kg_extract_build/tests/test_normative_scope.py kg_extract_build/tests/test_normative_production.py -q
19 passed in 1.03s

$env:PYTHONPATH='.'; $env:PYTHONIOENCODING='utf-8'; conda run -n env_agent python -m pytest kg_extract_build/tests -q
353 passed, 1 skipped, 51 subtests passed in 4.98s
```
