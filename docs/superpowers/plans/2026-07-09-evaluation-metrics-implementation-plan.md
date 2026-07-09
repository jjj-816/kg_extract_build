# Evaluation Metrics Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个可在 Streamlit 中选择历史实验、读取人工标注三元组文件夹、计算评估指标并把结果保存到 MySQL 的实验评估模块。

**Architecture:** 第一版以 MySQL 历史实验为模型输出来源，以本机 gold 标注文件夹为人工真值来源。新增 `evaluation.py` 承担纯计算与文件加载，`persistence.py` 承担数据库读写，`dashboard_evaluation.py` 承担页面交互，`dashboard.py` 只负责挂载入口。

**Tech Stack:** Python 标准库、unittest、Streamlit、PyMySQL、现有 `KGSchema`、现有 MySQL 实验表。

## Global Constraints

- 第一版只做严格匹配，不做语义相似匹配。
- 第一版不调用 LLM 判断幻觉或证据充分性。
- 第一版不做人工标注编辑器，只读取用户已经准备好的标注文件夹。
- 第一版不删除或覆盖已有评估记录；重新计算保存为新的评估记录。
- 重复评估识别使用 `run_id + gold_hash`，不使用 `gold_path` 作为唯一依据。
- 模型输出第一版优先从 MySQL 读取 `kg_triplet.stage='final'`。
- 人工标注文件同时支持 debug 对象格式和简化数组格式。
- 提交信息使用中文。

---

## File Structure

- Create: `kg_extract_build/evaluation.py` — gold 文件夹加载、gold_hash、三元组规范化、指标计算、预览摘要。
- Create: `kg_extract_build/dashboard_evaluation.py` — Streamlit “实验评估”页面。
- Modify: `kg_extract_build/schema.sql` — 新增 `kg_evaluation_run`、`kg_evaluation_metric`。
- Modify: `kg_extract_build/persistence.py` — 查询历史实验、读取评估输入、查询已有评估、保存评估结果。
- Modify: `kg_extract_build/dashboard.py` — 挂载评估页面入口。
- Tests: `kg_extract_build/tests/test_evaluation.py`、`test_schema_sql.py`、`test_experiment_tracking.py`、`test_dashboard_evaluation.py`。

---

### Task 1: 核心评估数据结构、gold 加载与 hash

**Files:**
- Create: `kg_extract_build/evaluation.py`
- Create: `kg_extract_build/tests/test_evaluation.py`

**Interfaces:**
- Produces `TripletKey = tuple[str, str, str, str, str]`
- Produces `GoldAnnotations(root: Path, documents: dict[str, list[TripletKey]], errors: list[dict[str, str]])`
- Produces `normalize_triplet(item, schema=None) -> TripletKey | None`
- Produces `load_gold_annotations(root: Path, schema=None) -> GoldAnnotations`
- Produces `compute_gold_hash(root: Path) -> str`

- [ ] **Step 1: Write failing tests**

Create `kg_extract_build/tests/test_evaluation.py` with tests that:

```python
# 1. create temp gold/文档A/实体.json using {"entity": "A", "triplets": [...]}
# 2. create temp gold/文档A/实体2.json using [...] array format
# 3. assert load_gold_annotations(root).documents["文档A"] has two triplets
# 4. create malformed broken.json and assert errors length is 1
# 5. compute hash before/after file content change and assert the hash changes
```

Use this exact command:

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_evaluation -q
```

Expected before implementation: `ModuleNotFoundError` for `kg_extract_build.evaluation`.

- [ ] **Step 2: Implement `evaluation.py` gold loading**

Implement:

```python
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

TripletKey = tuple[str, str, str, str, str]
TRIPLET_FIELDS = ("head", "head_type", "relation", "tail", "tail_type")

@dataclass(frozen=True)
class GoldAnnotations:
    root: Path
    documents: dict[str, list[TripletKey]] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    @property
    def triplet_count(self) -> int:
        return sum(len(v) for v in self.documents.values())
```

`normalize_triplet()` must trim strings, require `head/relation/tail`, and optionally call `schema.normalize_entity_type()` and `schema.normalize_relation()`.

`load_gold_annotations()` must recurse `*.json`, use parent directory name as document key, accept object-with-`triplets` and array payloads, and collect parse errors without stopping.

`compute_gold_hash()` must hash each relative json path and raw bytes in sorted order using SHA256.

- [ ] **Step 3: Verify and commit**

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_evaluation -q
git add kg_extract_build/evaluation.py kg_extract_build/tests/test_evaluation.py
git commit -m "实现：加载评估标注数据"
```

---

### Task 2: 指标计算

**Files:**
- Modify: `kg_extract_build/evaluation.py`
- Modify: `kg_extract_build/tests/test_evaluation.py`

**Interfaces:**
- Consumes `TripletKey` and `normalize_triplet()` from Task 1.
- Produces `MetricValue(name, value, numerator, denominator, details)`.
- Produces `ScoreBreakdown(precision, recall, f1, true_positive, false_positive, false_negative, tp_items, fp_items, fn_items)`.
- Produces `EvaluationResult(overall, by_document, matched_documents, missing_gold_documents, extra_gold_documents)`.
- Produces `compute_prf(model_items: set[tuple], gold_items: set[tuple]) -> ScoreBreakdown`.
- Produces `evaluate_documents(model, gold, documents, evidence, schema=None) -> EvaluationResult`.

- [ ] **Step 1: Write failing metric tests**

Append tests to `test_evaluation.py`:

```python
# compute_prf({("A",), ("B",)}, {("A",), ("C",)})
# assert TP=1, FP=1, FN=1, precision=0.5, recall=0.5, f1=0.5

# model 文档A has two triplets, gold 文档A has one matching triplet
# assert triplet_precision=0.5, triplet_recall=1.0
# evidence contains only first triplet tail, assert evidence_coverage=0.5 and hallucination_rate=0.5
```

Run:

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_evaluation -q
```

Expected: FAIL because `compute_prf` and `evaluate_documents` are missing.

- [ ] **Step 2: Implement metric functions**

In `evaluation.py`, add dataclasses and helpers:

```python
@dataclass(frozen=True)
class MetricValue:
    name: str
    value: float
    numerator: float | None = None
    denominator: float | None = None
    details: dict[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class ScoreBreakdown:
    precision: float
    recall: float
    f1: float
    true_positive: int
    false_positive: int
    false_negative: int
    tp_items: list[tuple]
    fp_items: list[tuple]
    fn_items: list[tuple]

@dataclass(frozen=True)
class EvaluationResult:
    overall: dict[str, MetricValue]
    by_document: dict[str, dict[str, MetricValue]]
    matched_documents: list[str]
    missing_gold_documents: list[str]
    extra_gold_documents: list[str]
```

Implement `compute_prf()` using strict set intersection. Empty behavior must follow the design: both empty gives 1.0/1.0/1.0; model empty gold non-empty gives precision 1.0, recall 0.0, f1 0.0; model non-empty gold empty gives precision 0.0, recall 1.0, f1 0.0.

Implement internal helpers:

```python
_entities(triplets) -> set[(name, type)]
_relations(triplets) -> set[(head, relation, tail)]
_invalid_count(triplets, schema) -> tuple[int, list[TripletKey]]
_coverage_counts(triplets, document_text, evidence_map) -> tuple[int, int, list[TripletKey]]
```

`evaluate_documents()` must:

1. Match documents by document key.
2. Compute entity/relation/triplet P/R/F1 over matched documents.
3. Compute invalid relation rate with `schema.is_relation_allowed(relation, head_type, tail_type)` when schema is available.
4. Compute evidence coverage when tail appears in evidence text or document text.
5. Compute hallucination rate as unsupported count divided by model triplet count for matched documents.
6. Include document-level triplet P/R/F1 in `by_document`.

- [ ] **Step 3: Verify and commit**

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_evaluation -q
git add kg_extract_build/evaluation.py kg_extract_build/tests/test_evaluation.py
git commit -m "实现：计算实验评估指标"
```

---

### Task 3: 评估预览和历史评估识别

**Files:**
- Modify: `kg_extract_build/evaluation.py`
- Modify: `kg_extract_build/tests/test_evaluation.py`

**Interfaces:**
- Produces `build_preview(model_documents: set[str], gold: GoldAnnotations, model_triplet_count: int, existing_evaluations: list[dict]) -> dict[str, object]`.

- [ ] **Step 1: Write failing preview test**

Add test:

```python
# model_documents={"文档A", "文档B"}
# gold.documents={"文档A": [triplet], "文档C": [triplet]}
# existing_evaluations=[{"evaluation_id": "e1"}]
# assert model_document_count=2, gold_document_count=2, matched_document_count=1
# assert missing_gold_documents=["文档B"], extra_gold_documents=["文档C"]
# assert gold_triplet_count=2, model_triplet_count=3, existing_evaluation_count=1
```

- [ ] **Step 2: Implement `build_preview()`**

Return keys:

```python
{
  "model_document_count": int,
  "gold_document_count": int,
  "matched_document_count": int,
  "matched_documents": list[str],
  "missing_gold_documents": list[str],
  "extra_gold_documents": list[str],
  "gold_triplet_count": int,
  "model_triplet_count": int,
  "parse_error_count": int,
  "parse_errors": list[dict[str, str]],
  "existing_evaluation_count": int,
  "existing_evaluations": list[dict],
}
```

- [ ] **Step 3: Verify and commit**

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_evaluation -q
git add kg_extract_build/evaluation.py kg_extract_build/tests/test_evaluation.py
git commit -m "实现：生成评估预览信息"
```

---

### Task 4: MySQL 表结构

**Files:**
- Modify: `kg_extract_build/schema.sql`
- Modify: `kg_extract_build/tests/test_schema_sql.py`

**Interfaces:**
- Produces table `kg_evaluation_run`.
- Produces table `kg_evaluation_metric`.

- [ ] **Step 1: Write failing schema test**

Add assertions in `test_schema_sql.py`:

```python
schema_sql = Path("kg_extract_build/schema.sql").read_text(encoding="utf-8")
self.assertIn("CREATE TABLE IF NOT EXISTS kg_evaluation_run", schema_sql)
self.assertIn("CREATE TABLE IF NOT EXISTS kg_evaluation_metric", schema_sql)
self.assertIn("gold_hash CHAR(64) NOT NULL", schema_sql)
self.assertIn("INDEX idx_kg_eval_run_gold (run_id, gold_hash)", schema_sql)
self.assertIn("CONSTRAINT fk_kg_eval_run FOREIGN KEY (run_id)", schema_sql)
self.assertIn("CONSTRAINT fk_kg_eval_metric_run FOREIGN KEY (evaluation_id)", schema_sql)
```

Run:

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_schema_sql -q
```

Expected: FAIL because the tables are missing.

- [ ] **Step 2: Add SQL tables**

Append to `schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS kg_evaluation_run (
    evaluation_id CHAR(36) PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    gold_path VARCHAR(1024) NOT NULL,
    gold_hash CHAR(64) NOT NULL,
    metric_config_json JSON NULL,
    summary_json JSON NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_kg_eval_run_gold (run_id, gold_hash),
    CONSTRAINT fk_kg_eval_run FOREIGN KEY (run_id)
        REFERENCES kg_experiment_run(run_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_evaluation_metric (
    metric_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    evaluation_id CHAR(36) NOT NULL,
    scope_type VARCHAR(32) NOT NULL,
    scope_name VARCHAR(512) NOT NULL,
    metric_name VARCHAR(128) NOT NULL,
    metric_value DOUBLE NOT NULL,
    numerator DOUBLE NULL,
    denominator DOUBLE NULL,
    details_json JSON NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_kg_eval_metric_scope (evaluation_id, scope_type, metric_name),
    CONSTRAINT fk_kg_eval_metric_run FOREIGN KEY (evaluation_id)
        REFERENCES kg_evaluation_run(evaluation_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

- [ ] **Step 3: Verify and commit**

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_schema_sql -q
git add kg_extract_build/schema.sql kg_extract_build/tests/test_schema_sql.py
git commit -m "实现：新增评估结果数据表"
```

---

### Task 5: 持久化层读取评估输入与保存结果

**Files:**
- Modify: `kg_extract_build/persistence.py`
- Modify: `kg_extract_build/tests/test_experiment_tracking.py`

**Interfaces:**
- Consumes `EvaluationResult` from Task 2.
- Produces store methods:
  - `list_experiment_runs(self, limit=100) -> list[dict]`
  - `load_evaluation_input(self, run_id: str) -> dict[str, object]`
  - `list_evaluations(self, run_id: str, gold_hash: str | None = None) -> list[dict]`
  - `save_evaluation(self, run_id: str, gold_path: str, gold_hash: str, metric_config: dict, result: EvaluationResult) -> str`

- [ ] **Step 1: Write failing MemoryExperimentStore test**

Add test in `test_experiment_tracking.py`:

```python
# create MemoryExperimentStore
# start_run()
# build EvaluationResult(overall={"triplet_f1": MetricValue("triplet_f1", 0.75)}, ...)
# call save_evaluation(run_id, "D:/gold", "a" * 64, {"matching": "strict"}, result)
# call list_evaluations(run_id, gold_hash="a" * 64)
# assert one row, same evaluation_id, triplet_f1 == 0.75
```

Run:

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_experiment_tracking -q
```

Expected: FAIL because methods are missing.

- [ ] **Step 2: Implement MemoryExperimentStore methods**

Add in `MemoryExperimentStore.__init__`:

```python
self.evaluation_runs = []
self.evaluation_metrics = []
```

Implement methods with the exact signatures above. `load_evaluation_input()` must return:

```python
{
  "documents": {doc_stem: {"document_id": id, "file_name": file_name, "content": content}},
  "triplets": {doc_stem: [TripletKey, ...]},
  "evidence": {doc_stem: {TripletKey: [sentence, ...]}},
}
```

For Memory store, evidence can be `{}` in the first implementation if tests do not require it.

- [ ] **Step 3: Implement MySQLExperimentStore methods**

Use existing connection helpers and JSON serialization style in `persistence.py`. SQL queries required:

```sql
SELECT run_id, run_name, status, started_at, finished_at, config_snapshot
FROM kg_experiment_run
ORDER BY started_at DESC
LIMIT %s;
```

```sql
SELECT document_id, file_name, content
FROM kg_document
WHERE run_id=%s;
```

```sql
SELECT document_id, head, head_type, relation_name, tail, tail_type
FROM kg_triplet
WHERE run_id=%s AND stage='final';
```

```sql
SELECT evaluation_id, run_id, gold_path, gold_hash, summary_json, created_at
FROM kg_evaluation_run
WHERE run_id=%s AND (%s IS NULL OR gold_hash=%s)
ORDER BY created_at DESC;
```

`save_evaluation()` inserts one `kg_evaluation_run` row and metric rows for:

- all `result.overall` metrics with `scope_type='overall'`, `scope_name='all'`;
- all `result.by_document[doc]` metrics with `scope_type='document'`, `scope_name=doc`.

- [ ] **Step 4: Verify and commit**

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_experiment_tracking -q
git add kg_extract_build/persistence.py kg_extract_build/tests/test_experiment_tracking.py
git commit -m "实现：保存实验评估结果"
```

---

### Task 6: Streamlit 实验评估页面

**Files:**
- Create: `kg_extract_build/dashboard_evaluation.py`
- Modify: `kg_extract_build/dashboard.py`
- Create: `kg_extract_build/tests/test_dashboard_evaluation.py`

**Interfaces:**
- Consumes store methods from Task 5.
- Consumes `load_gold_annotations()`、`compute_gold_hash()`、`build_preview()`、`evaluate_documents()` from `evaluation.py`.
- Produces `format_run_label(row: dict) -> str`.
- Produces `render_evaluation_page() -> None`.

- [ ] **Step 1: Write failing dashboard helper test**

Create `test_dashboard_evaluation.py`:

```python
# import format_run_label
# row = {"run_id": "abc123", "run_name": "实验一", "status": "completed", "started_at": "2026-07-09"}
# assert label contains 实验一, completed, abc123
```

Run:

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_dashboard_evaluation -q
```

Expected: FAIL because module is missing.

- [ ] **Step 2: Implement `dashboard_evaluation.py`**

Create helpers:

```python
def format_run_label(row: dict) -> str:
    run_id = str(row.get("run_id", ""))
    run_name = str(row.get("run_name") or "未命名实验")
    status = str(row.get("status") or "unknown")
    started_at = str(row.get("started_at") or "")
    return f"{run_name} | {status} | {started_at} | {run_id[:8]}"
```

`render_evaluation_page()` must:

1. Create `MySQLExperimentStore.from_env()` inside try/except.
2. Show warning and return when MySQL cannot connect.
3. List historical runs using `list_experiment_runs(limit=100)`.
4. Let user choose one run.
5. Let user input local gold folder path.
6. Load schema using `KGSchema(resolve_schema_path())`.
7. Compute `gold_hash` with `compute_gold_hash()`.
8. Load gold with `load_gold_annotations()`.
9. Load model input with `store.load_evaluation_input(run_id)`.
10. Query existing evaluations with `store.list_evaluations(run_id, gold_hash)`.
11. Render preview metrics: history document count, gold document count, matched document count, gold/model triplet counts, parse errors, existing evaluation count.
12. On “计算指标”, call `evaluate_documents()` and store result in `st.session_state`.
13. Show metric cards for `entity_f1`, `relation_f1`, `triplet_f1`, `invalid_relation_rate`, `hallucination_rate`, `evidence_coverage`.
14. On “保存评估结果”, call `store.save_evaluation()` and show saved `evaluation_id`.

- [ ] **Step 3: Mount page in `dashboard.py`**

Add import:

```python
from kg_extract_build.dashboard_evaluation import render_evaluation_page
```

Add a page option named `实验评估` in the existing navigation and route it to `render_evaluation_page()`.

- [ ] **Step 4: Verify and commit**

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_dashboard_evaluation kg_extract_build.tests.test_dashboard_smoke -q
git add kg_extract_build/dashboard_evaluation.py kg_extract_build/dashboard.py kg_extract_build/tests/test_dashboard_evaluation.py
git commit -m "实现：新增实验评估页面"
```

---

### Task 7: 文档、集成验证与收尾

**Files:**
- Modify: `kg_extract_build/README.md`
- Modify: `kg_extract_build/agent.md`

**Interfaces:**
- Consumes all previous tasks.
- Produces user-facing evaluation workflow docs.

- [ ] **Step 1: Update README**

Add section `## 实验评估` explaining:

```markdown
评估模块用于把历史实验输出和人工标注三元组进行对比。使用前需要先启用并初始化 MySQL，确保历史实验已经写入 `kg_experiment_run`、`kg_document` 和 `kg_triplet`。

人工标注文件夹推荐结构：

```text
gold_annotations/
  文档名/
    实体名.json
```

每个 JSON 文件可以是当前 debug 文件格式，也可以直接是三元组数组。进入 Streamlit 后打开“实验评估”，选择历史实验，输入标注文件夹路径，预览匹配情况后点击“计算指标”。保存后结果会写入 `kg_evaluation_run` 和 `kg_evaluation_metric`。
```

- [ ] **Step 2: Update agent.md**

Add operational notes:

```markdown
## 实验评估模块

- 评估入口在 Streamlit 的“实验评估”页面。
- 模型结果优先读取 MySQL 中 `kg_triplet.stage='final'` 的三元组。
- 人工标注通过本机文件夹路径读取，不会写回标注文件。
- 重复评估识别使用 `run_id + gold_hash`；同一标注内容再次评估会提示历史记录，但允许保存为新的评估记录。
- 第一版使用严格匹配，适合论文实验复现；别名归一化和语义匹配属于后续增强。
```

- [ ] **Step 3: Run targeted tests**

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest kg_extract_build.tests.test_evaluation kg_extract_build.tests.test_schema_sql kg_extract_build.tests.test_experiment_tracking kg_extract_build.tests.test_dashboard_evaluation -q
```

Expected: OK.

- [ ] **Step 4: Run full tests**

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m unittest discover -s kg_extract_build/tests -q
```

Expected: OK.

- [ ] **Step 5: Compile package**

```powershell
& 'D:\ProgramData\anaconda3\envs\env_agent\python.exe' -m compileall -q kg_extract_build
```

Expected: exit code 0.

- [ ] **Step 6: Check git status**

```powershell
git status --short --branch
```

Expected: only intended files are modified. Do not add `references_shale_gas_graphrag.csv` or `references_shale_gas_graphrag.md` unless the user explicitly asks.

- [ ] **Step 7: Commit docs**

```powershell
git add kg_extract_build/README.md kg_extract_build/agent.md
git commit -m "文档：补充实验评估使用说明"
```

---

## Self-Review

- Spec coverage: Task 1 covers gold loading and gold_hash; Task 2 covers all metrics; Task 3 covers preview and existing evaluation counts; Task 4 covers schema; Task 5 covers persistence; Task 6 covers Streamlit; Task 7 covers docs and verification.
- Placeholder scan: No unresolved placeholder markers. Every task has concrete files, interfaces, tests, commands, and commit messages.
- Type consistency: `TripletKey`、`GoldAnnotations`、`MetricValue`、`EvaluationResult` are introduced before downstream use. Store method names are consistent between Task 5 and Task 6.
- Scope check: The plan implements the approved first version only: strict matching, local gold folder, MySQL persistence, Streamlit visualization. Semantic matching, annotation editor, and LLM-based evidence judgment remain outside scope.

