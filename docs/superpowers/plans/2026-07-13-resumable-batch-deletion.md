# Resumable Batch Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a MySQL/Milvus batch deletion resumable from persisted state, without asking operators which store to delete next.

**Architecture:** Add `deletion_state` to experiment runs and expose persistence methods for state transitions. The dashboard service writes a pending SQL state only after vector deletion succeeds; a later resume action reads that state and performs only the parent SQL deletion.

**Tech Stack:** Python 3, Streamlit, PyMySQL/InnoDB, optional Milvus, unittest.

## Global Constraints

- Do not delete existing batches during development or tests.
- Do not touch `references_shale_gas_graphrag.csv` or `references_shale_gas_graphrag.md`.
- Do not create a Git commit.
- `deletion_state` values are `active` and `vectors_deleted_sql_pending`; SQL parent deletion is the terminal `deleted` operation.

### Task 1: Persist and expose deletion state

**Files:**
- Modify: `kg_extract_build/schema.sql`, `kg_extract_build/persistence.py`
- Test: `kg_extract_build/tests/test_experiment_tracking.py`

- [ ] **Step 1: Write failing state-transition tests.**

```python
def test_memory_store_marks_and_reads_pending_vector_deletion(self):
    store = MemoryExperimentStore()
    run_id = store.start_run("pending", {}, {}, "")
    self.assertEqual(store.get_deletion_state(run_id), "active")
    self.assertTrue(store.mark_vectors_deleted_sql_pending(run_id))
    self.assertEqual(store.get_deletion_state(run_id), "vectors_deleted_sql_pending")
```

- [ ] **Step 2: Verify RED.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_experiment_tracking -v`

Expected: missing state-method failure.

- [ ] **Step 3: Implement the minimal contract.**

Add `get_deletion_state(run_id) -> str | None` and `mark_vectors_deleted_sql_pending(run_id) -> bool` to `BaseExperimentStore`. Set `deletion_state: "active"` when the memory store starts a run; update only that run in memory. For MySQL, use parameterized `SELECT deletion_state FROM kg_experiment_run WHERE run_id=%s` and `UPDATE kg_experiment_run SET deletion_state='vectors_deleted_sql_pending' WHERE run_id=%s AND deletion_state='active'`, returning `cursor.rowcount > 0`.

Add `deletion_state VARCHAR(32) NOT NULL DEFAULT 'active'` to the table definition and a migration-safe `ALTER TABLE kg_experiment_run ADD COLUMN deletion_state ...` execution path in the schema initialization code, guarded so existing databases do not fail when the column already exists.

- [ ] **Step 4: Verify GREEN.**

Run the Task 1 test command; expected: all pass.

### Task 2: Resume-aware dashboard deletion service

**Files:**
- Modify: `kg_extract_build/dashboard.py`
- Test: `kg_extract_build/tests/test_dashboard_batches.py`

- [ ] **Step 1: Write failing service tests.**

```python
def test_vector_success_sql_failure_leaves_pending_state(self):
    result = delete_run_with_vectors({}, "run-123")
    self.assertEqual(result.state, "vectors_deleted_sql_pending")
    store.mark_vectors_deleted_sql_pending.assert_called_once_with("run-123")

def test_resume_pending_deletion_does_not_call_vector_store(self):
    result = resume_pending_run_deletion({}, "run-123")
    self.assertTrue(result.deleted)
    build_vector_store.assert_not_called()
```

- [ ] **Step 2: Verify RED.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_dashboard_batches -v`

Expected: missing result/resume interface failure.

- [ ] **Step 3: Implement the service.**

Define a result dataclass with `deleted: bool`, `state: str`, and `message: str`. `delete_run_with_vectors` must: create the SQL store; reject non-`active` runs; delete and close vectors; call `mark_vectors_deleted_sql_pending`; then call `delete_run`. If the final SQL delete is false or raises, return/raise a result that retains `vectors_deleted_sql_pending`. `resume_pending_run_deletion` must verify the persisted state, call only `delete_run`, and return success only when its rowcount is positive.

- [ ] **Step 4: Verify GREEN.**

Run the Task 2 command; expected: all dashboard tests pass.

### Task 3: Render deterministic recovery controls and document them

**Files:**
- Modify: `kg_extract_build/dashboard.py`, `kg_extract_build/README.md`
- Test: `kg_extract_build/tests/test_dashboard_batches.py`

- [ ] **Step 1: Write a failing pending-state UI test.**

```python
def test_pending_run_shows_resume_button_and_calls_sql_only_resume(self):
    page = self.render_runs_page(
        dict(self.selected_completed, deletion_state="vectors_deleted_sql_pending"),
        confirmed=True,
        clicked=True,
    )
    resume_pending_run_deletion.assert_called_once()
```

- [ ] **Step 2: Verify RED.**

Run the dashboard test command; expected: no pending-state control.

- [ ] **Step 3: Implement UI and notes.**

Include `deletion_state` in list/detail queries. For pending runs, show a warning that vectors are already removed and render a confirmation-labelled “恢复删除（仅删除 SQL 数据）” button wired exclusively to `resume_pending_run_deletion`. Preserve the original confirmation-only flow for active, non-running runs. Document the states, automatic resume behavior, and the irreversible vector phase.

- [ ] **Step 4: Verify and review boundary.**

Run:
`D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest discover -s kg_extract_build\tests -p "test_*.py" -v`

Run:
`D:\ProgramData\anaconda3\envs\env_agent\python.exe -m py_compile kg_extract_build\dashboard.py kg_extract_build\persistence.py`

Run: `git diff --check`

Expected: all tests pass, compile exits 0, no whitespace errors, and no protected-reference diff.
