# Batch Deletion and Unknown-Type Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator safely remove one obsolete experiment batch and all of its persisted/vector data, and prevent final triplets with an unclassified endpoint by retrying type completion once.

**Architecture:** Keep destructive deletion behind a persistence/vector-store boundary and expose it only from the experiment-batch page after an explicit confirmation. Keep triplet extraction responsible for requesting a one-time structured type completion; both raw parsing and correction share a strict final-type predicate so a retry failure cannot reach `kg_triplet.stage='final'`.

**Tech Stack:** Python 3, Streamlit, PyMySQL/InnoDB foreign-key cascades, optional Milvus (`pymilvus`), `unittest`.

## Global Constraints

- Work on the `evaluate` branch; do not delete existing batches during development or tests.
- A deletion is scoped to exactly one selected `run_id`; all SQL is parameterized.
- MySQL child records rely on the existing `ON DELETE CASCADE` foreign keys; Milvus vectors are explicitly deleted by `run_id` before deleting the SQL parent.
- Deletion of a `running` batch is disabled; the operator must select a non-running batch and tick a confirmation checkbox containing its full `run_id`.
- A model may receive exactly one additional call per candidate triplet with an unknown head or tail type. If its normalized type is still `未分类`, the triplet is rejected and is never persisted as a final triplet.
- Do not alter the earlier pre-processing work or `references_shale_gas_graphrag.csv` / `references_shale_gas_graphrag.md`.
- Do not create a Git commit unless the user explicitly asks for one.

---

## File Structure

- Modify `kg_extract_build/persistence.py`: define `delete_run(run_id) -> bool` on the store contract; implement matching in-memory deletion and MySQL parent-row deletion.
- Modify `kg_extract_build/vector_store.py`: define `delete_segments_by_run(run_id) -> None` for null and Milvus stores.
- Modify `kg_extract_build/dashboard.py`: add a destructive, two-step batch-deletion panel to `runs_page` and a small committed SQL write helper.
- Modify `kg_extract_build/triplets.py`: add one-time type-completion parsing and strict endpoint validation before final acceptance.
- Modify `kg_extract_build/schema.py`: centralize the predicate that says whether a normalized entity type is usable in final output.
- Modify `kg_extract_build/tests/test_experiment_tracking.py`: cover in-memory batch deletion and unrelated-run preservation.
- Modify `kg_extract_build/tests/test_triplet_batching.py`: cover one retry, successful normalization, failed retry rejection, and no retry for fully typed triplets.
- Create `kg_extract_build/tests/test_dashboard_batches.py`: cover confirmation gating and the dashboard deletion callback without connecting to MySQL/Milvus.

## Task 1: Batch deletion contracts and persistence semantics

**Files:**
- Modify: `kg_extract_build/persistence.py:35-79, 96-245, 350-700`
- Test: `kg_extract_build/tests/test_experiment_tracking.py`

**Interfaces:**
- Produces `BaseExperimentStore.delete_run(run_id: str) -> bool`.
- Produces `MemoryExperimentStore.delete_run(run_id: str) -> bool`.
- Produces `MySQLExperimentStore.delete_run(run_id: str) -> bool`.

- [ ] **Step 1: Write failing tests for deletion isolation.**

```python
def test_memory_store_deletes_only_selected_run_and_children(self):
    store = MemoryExperimentStore()
    delete_id = store.start_run("delete", {}, {}, "")
    keep_id = store.start_run("keep", {}, {}, "")
    delete_doc = store.start_document(delete_id, "delete.md", "case", "a", "text")
    keep_doc = store.start_document(keep_id, "keep.md", "case", "b", "text")
    store.save_chunks(delete_id, delete_doc, "retrieval_sentence", [{"index": 0, "content": "x"}])
    store.save_chunks(keep_id, keep_doc, "retrieval_sentence", [{"index": 0, "content": "y"}])

    self.assertTrue(store.delete_run(delete_id))
    self.assertNotIn(delete_id, store.runs)
    self.assertIn(keep_id, store.runs)
    self.assertEqual([row["run_id"] for row in store.chunks], [keep_id])
    self.assertFalse(store.delete_run(delete_id))
```

- [ ] **Step 2: Run the focused test and verify it fails because `delete_run` is absent.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_experiment_tracking.ExperimentRecorderTests.test_memory_store_deletes_only_selected_run_and_children -v`

Expected: `AttributeError: 'MemoryExperimentStore' object has no attribute 'delete_run'`.

- [ ] **Step 3: Add the store method and minimal deletion implementations.**

```python
class BaseExperimentStore:
    def delete_run(self, run_id):
        return False

class MemoryExperimentStore(BaseExperimentStore):
    def delete_run(self, run_id):
        if run_id not in self.runs:
            return False
        document_ids = {key for key, value in self.documents.items() if value["run_id"] == run_id}
        self.runs.pop(run_id)
        self.documents = {key: value for key, value in self.documents.items() if key not in document_ids}
        self.chunks = [row for row in self.chunks if row["run_id"] != run_id]
        self.llm_calls = [row for row in self.llm_calls if row["run_id"] != run_id]
        self.entities = [row for row in self.entities if row["run_id"] != run_id]
        self.retrieval_results = [row for row in self.retrieval_results if row["run_id"] != run_id]
        self.triplets = [row for row in self.triplets if row["run_id"] != run_id]
        self.evaluation_runs = [row for row in self.evaluation_runs if row["run_id"] != run_id]
        return True

class MySQLExperimentStore(BaseExperimentStore):
    def delete_run(self, run_id):
        return self._write("DELETE FROM kg_experiment_run WHERE run_id=%s", (run_id,)) is not None
```

Adjust `_write` or add a dedicated `delete_run` SQL execution path so the return value is based on `cursor.rowcount`, not `lastrowid`; it must return `False` for an absent ID. Do not manually delete child SQL tables: `schema.sql` already cascades `kg_document`, chunks, LLM calls, entities, retrieval results, triplets, evaluations, and evaluation metrics from the run parent.

- [ ] **Step 4: Run the focused test and existing persistence tests.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_experiment_tracking -v`

Expected: all tests pass.

## Task 2: Remove associated Milvus vectors before SQL cascade

**Files:**
- Modify: `kg_extract_build/vector_store.py:6-79`
- Test: `kg_extract_build/tests/test_experiment_tracking.py`

**Interfaces:**
- Produces `NullVectorStore.delete_segments_by_run(run_id: str) -> None`.
- Produces `MilvusSegmentStore.delete_segments_by_run(run_id: str) -> None`.

- [ ] **Step 1: Write the failing Milvus delegation test with a fake client.**

```python
def test_milvus_store_deletes_vectors_by_exact_run_id(self):
    store = MilvusSegmentStore.__new__(MilvusSegmentStore)
    store.collection_name = "segments"
    store.client = FakeMilvusClient()

    store.delete_segments_by_run("run-123")

    self.assertEqual(store.client.calls, [("segments", 'run_id == "run-123"')])
```

- [ ] **Step 2: Run the focused test and verify it fails because the method is absent.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_experiment_tracking.VectorStoreDeletionTests.test_milvus_store_deletes_vectors_by_exact_run_id -v`

Expected: `AttributeError` for `delete_segments_by_run`.

- [ ] **Step 3: Implement deletion with a fixed, UUID-safe filter.**

```python
class NullVectorStore:
    def delete_segments_by_run(self, run_id):
        return None

class MilvusSegmentStore:
    def delete_segments_by_run(self, run_id):
        escaped = str(run_id).replace("\\", "\\\\").replace('"', '\\"')
        self.client.delete(
            collection_name=self.collection_name,
            filter=f'run_id == "{escaped}"',
        )
```

The dashboard must call this before `MySQLExperimentStore.delete_run`; if Milvus deletion raises an error, do not execute the SQL delete and show the error, avoiding an orphaned vector set.

- [ ] **Step 4: Run the focused test.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_experiment_tracking.VectorStoreDeletionTests -v`

Expected: all vector deletion tests pass.

## Task 3: Add a two-step destructive control to the experiment-batch page

**Files:**
- Modify: `kg_extract_build/dashboard.py:91-111, 220-267`
- Create: `kg_extract_build/tests/test_dashboard_batches.py`

**Interfaces:**
- Produces `delete_run_with_vectors(config: dict, run_id: str) -> bool` in `dashboard.py`.
- Consumes the Task 1 `MySQLExperimentStore.delete_run` and Task 2 `build_vector_store().delete_segments_by_run`.

- [ ] **Step 1: Write failing dashboard tests for the safety gate.**

```python
def test_delete_action_is_not_called_without_confirmation(self):
    service = Mock()
    self.render_runs_page(selected={"status": "completed", "confirmed": False}, service=service)
    service.assert_not_called()

def test_confirmed_completed_run_deletes_vectors_then_sql(self):
    events = []
    self.render_runs_page(selected={"status": "completed", "confirmed": True}, events=events)
    self.assertEqual(events, ["vectors", "sql"])

def test_running_run_has_no_enabled_delete_button(self):
    page = self.render_runs_page(selected={"status": "running", "confirmed": True})
    self.assertTrue(page.delete_disabled)
```

- [ ] **Step 2: Run the dashboard test and verify it fails before the deletion panel exists.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_dashboard_batches -v`

Expected: failure because `delete_run_with_vectors` and the deletion controls do not exist.

- [ ] **Step 3: Implement the UI and transaction order.**

Add a danger expander below the selected run’s detail tabs. It displays the immutable run name, ID, status, document count, and final-triplet count. It contains:

```python
confirmed = st.checkbox(
    f"我确认永久删除批次 {run_id} 及其全部关联数据",
    key=f"confirm_delete_{run_id}",
)
if st.button("永久删除此实验批次", type="primary", disabled=(status == "running" or not confirmed)):
    deleted = delete_run_with_vectors(config, run_id)
    if deleted:
        st.session_state.pop("preferred_run_id", None)
        st.success("实验批次及关联数据已删除。")
        st.rerun()
    st.warning("运行中的批次不能删除。") if status == "running" else None
```

`delete_run_with_vectors` builds the configured vector store, calls `delete_segments_by_run(run_id)`, closes it in `finally`, then instantiates `MySQLExperimentStore(config)` and calls `delete_run(run_id)`. If no SQL row is removed, show an informational result and do not claim success. Refresh the batch table only after success. Never issue a `DELETE` from the overview, documents, graph, evaluation, or LLM pages.

- [ ] **Step 4: Run dashboard smoke and new safety tests.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_dashboard_batches kg_extract_build.tests.test_dashboard_smoke -v`

Expected: all tests pass without a real database or Milvus service.

## Task 4: Define strict final-type validation and a one-time type-completion prompt

**Files:**
- Modify: `kg_extract_build/schema.py:114-139`
- Modify: `kg_extract_build/triplets.py:40-360, 400-435`
- Modify: `kg_extract_build/tests/test_triplet_batching.py`

**Interfaces:**
- Produces `Schema.is_final_entity_type_allowed(entity_type: str) -> bool`.
- Produces `TripletGenerator.complete_unknown_types(triplet: dict, context: str) -> dict | None`.
- `TripletGenerator._parse_triplets(...)` returns only triplets where both endpoint types pass `is_final_entity_type_allowed`.

- [ ] **Step 1: Write failing retry tests.**

```python
def test_unknown_tail_type_is_completed_once_then_accepted(self):
    generator = self.make_generator(['{"head_type":"设备工具","tail_type":"施工参数"}'])
    rows = generator._parse_triplets(
        '[{"head":"泡排车","relation":"HAS_PARAMETER","tail":"注入量","tail_type":"未分类"}]',
        "泡排车", "设备工具", "泡排车注入量", None,
    )
    self.assertEqual(rows, [{"head": "泡排车", "head_type": "设备工具", "relation": "HAS_PARAMETER", "tail": "注入量", "tail_type": "施工参数"}])
    self.assertEqual(generator.type_completion_call_count, 1)

def test_unknown_type_retry_still_unknown_is_rejected(self):
    generator = self.make_generator(['{"head_type":"未分类","tail_type":"未分类"}'])
    self.assertEqual(generator._parse_triplets(...), [])

def test_fully_typed_triplet_does_not_make_type_completion_call(self):
    generator = self.make_generator([])
    self.assertEqual(len(generator._parse_triplets(...)), 1)
    self.assertEqual(generator.type_completion_call_count, 0)
```

Also test a missing/invalid type, an out-of-schema type normalized to `未分类`, and an LLM parse exception: each must yield no final triplet after exactly one retry.

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_triplet_batching -v`

Expected: failures because no strict final-type predicate or retry exists.

- [ ] **Step 3: Implement strict schema validation.**

```python
def is_final_entity_type_allowed(self, entity_type):
    normalized = self.normalize_entity_type(entity_type)
    return bool(normalized) and normalized != UNKNOWN_TYPE
```

Keep `is_relation_allowed` permissive for intermediate extraction so existing callers remain compatible; use `is_final_entity_type_allowed` only at final-output gates.

- [ ] **Step 4: Implement exactly one structured completion call.**

For every parsed candidate with a missing/unknown head or tail type, call the same configured LLM once with the original `head`, `relation`, `tail`, current known types, and evidence context. Require a JSON object exactly shaped as:

```json
{"head_type": "Schema实体类型", "tail_type": "Schema实体类型"}
```

Normalize both returned values with `schema.normalize_entity_type`. Retain the original entity strings and relation; the completion prompt must not create, rename, split, or merge entities. If either normalized value remains `UNKNOWN_TYPE`, is empty, the call errors, or JSON is invalid, return `None`. Recheck `schema.is_relation_allowed(relation, head_type, tail_type)` after completion. Record the call through the existing LLM recorder as stage `triplet_type_completion`, retaining prompt, raw response, parsed result, latency, and error details.

Apply the same `is_final_entity_type_allowed(head_type/tail_type)` guard in `TripletCorrector.correct`, ensuring no unknown-type triplet can re-enter at correction.

- [ ] **Step 5: Run focused and regression tests.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_triplet_batching kg_extract_build.tests.test_pipeline_relation_batching kg_extract_build.tests.test_llm_call_options -v`

Expected: all tests pass; no test observes more than one type-completion call per candidate triplet.

## Task 5: End-to-end verification and operator documentation

**Files:**
- Modify: `kg_extract_build/README.md:172-220`
- Test: `kg_extract_build/tests/test_dashboard_batches.py`, `kg_extract_build/tests/test_triplet_batching.py`, `kg_extract_build/tests/test_experiment_tracking.py`

**Interfaces:**
- Documents the irreversible batch-deletion flow and the `triplet_type_completion` LLM stage.

- [ ] **Step 1: Add concise operator notes.**

Document that deleting a completed/failed batch removes its MySQL children and its Milvus segments, that running batches are protected, and that the action cannot be undone. Document that final triplets require both endpoint types to be in the active schema; unknown types trigger one completion attempt and are otherwise excluded.

- [ ] **Step 2: Run the full relevant regression suite.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest discover -s kg_extract_build\tests -p "test_*.py" -v`

Expected: all tests pass.

- [ ] **Step 3: Run static checks and review the change boundary.**

Run: `D:\ProgramData\anaconda3\envs\env_agent\python.exe -m py_compile kg_extract_build\dashboard.py kg_extract_build\persistence.py kg_extract_build\vector_store.py kg_extract_build\schema.py kg_extract_build\triplets.py`

Expected: exit code `0`.

Run: `git diff --check`

Expected: no whitespace errors. Confirm the diff excludes `references_shale_gas_graphrag.csv`, `references_shale_gas_graphrag.md`, and the existing unrelated pre-processing changes unless the user separately asks to include them.

## Plan Self-Review

- Coverage: Task 1/2/3 implement batch selection, confirmation, isolated deletion, SQL children, and Milvus vectors; Task 4 prevents unknown endpoints with one retry; Task 5 verifies and documents both behaviors.
- Constraints: no existing data is deleted during implementation, only non-running batches can be deleted from the UI, and no commit is included.
- Type consistency: `delete_run`, `delete_segments_by_run`, `is_final_entity_type_allowed`, and `complete_unknown_types` are defined before consumers and use the same `run_id`/type semantics throughout.
