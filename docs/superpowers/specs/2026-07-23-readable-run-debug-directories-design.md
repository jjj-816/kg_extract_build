# Readable Run Debug Directories Design

## Goal

Name newly created entity and triplet debug directories with the experiment's readable `run_name`, while retaining a short run identifier for uniqueness.

## Decision

For every new pipeline run, derive one directory component from the actual `PipelineConfig.run_name` supplied to `run_pipeline` (or the existing default selected before the run starts). Replace Windows-invalid filename characters (`/`, `\\`, `:`, `*`, `?`, `\"`, `<`, `>`, `|`) with `_`, trim the result, and append the first eight characters of `run_id`:

```
<sanitized-run-name>__<run-id[:8]>
```

For example, the run `实体对齐优化` with ID `65fea457-b8a8-4a32-a7d8-bd2c8f978124` writes to `实体对齐优化__65fea457` below both `shale_gas_entity_debug` and `shale_gas_triplets_debug`.

## Scope and Data Flow

`run_pipeline` already has both values immediately after `store.start_run(...)`. It will pass them to the shared run-debug-directory helper. Entity extraction writes and cache reads use the entity directory returned by that helper; triplet generation receives the corresponding triplet directory. This keeps every artifact from one run isolated under the same readable component.

Existing run-id-only folders are neither renamed nor deleted. They remain readable as historical artifacts. No database schema or stored run data changes.

## Edge Cases

- Different runs with the same name remain separate because of the short ID suffix.
- A blank or all-invalid-character name falls back to `run` before appending the suffix.
- The function returns a `Path` only; callers retain responsibility for creating artifact subdirectories, matching current behavior.

## Verification

Add unit tests for a normal Chinese name, Windows-invalid characters, a blank name, and two same-name runs with different IDs. Run the pipeline-control test suite to verify both entity and triplet consumers still receive isolated directories.
