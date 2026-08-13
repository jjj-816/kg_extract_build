# Task 4 Report — 2026-08-13

## Delivered

- Asset overview now classifies each version as `match`, `mismatch`, or `unknown` against its normative family using standard-code identity first and normalized name as a fallback.
- A `mismatch` asset is visibly warned in the normative dashboard and excluded from version candidates and enabled unified-corpus indexes, so it cannot be used as a substitute-chain candidate or formal audit source.
- Either a normalized name conflict or a standard-code conflict marks an asset `mismatch`; a matching standard code cannot mask a conflicting version name.
- Mismatched assets remain selectable in management UI for a separately confirmed safe disable or the existing confirmed destructive delete. After delete confirmation, the flow checks historical audit references and clears every vector index attached to the selected version through the vector-store lifecycle API before persistence records are removed.
- Safe-management operations use a separate selector that includes normal and mismatched indexes with explicit labels. The selected management index, not the first ready index, receives the confirmed disable/delete action.

## TDD evidence

- Red: asset-overview and dashboard-warning tests failed before the implementation because `family_consistency` and the warning did not exist.
- Red: enabled-index eligibility test failed before the implementation because a mismatched asset remained in the unified corpus.
- Red: a matching code plus conflicting name incorrectly produced `match`; a mismatched asset did not render confirmed management controls.
- Red: when a normal index preceded a mismatch, confirmed management actions targeted the normal index instead of allowing selection of the mismatch.
- Green: `conda run -n env_agent pytest kg_extract_build/tests/test_normative_persistence.py kg_extract_build/tests/test_dashboard_normative.py -q` → `13 passed`.

## Regression

```text
conda run -n env_agent pytest kg_extract_build/tests -q
361 passed, 1 skipped, 51 subtests passed in 5.11s
```

## Live-service acceptance — blocked without mutation

The read-only probe `conda run -n env_agent python -m kg_extract_build.scripts.production_probe` stopped before any read of normative assets because MySQL rejected the default unauthenticated connection: `OperationalError (1045): Access denied for user 'root'@'localhost' (using password: NO)`.

The worktree/process environment does not provide the required live MySQL/Milvus/release configuration.  Therefore the following required acceptance checks could not be performed: confirming the correct 《页岩气地面工程设计规范》 index metadata and readiness, identifying the two misfiled finite-space versions, obtaining the user's manual deletion confirmation, and running the requested real audit with durable retrieval traces.  No database, vector index, or version record was modified.

To resume, provide the live service configuration/credentials and have an authorized user manually confirm deletion of the identified wrong versions in the dashboard.  Then rerun the read-only asset check and the live audit acceptance.
