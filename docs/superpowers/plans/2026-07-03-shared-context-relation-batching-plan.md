# 共享上下文批量关系抽取实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将逐实体关系抽取改造成可切换的共享上下文批量流程，在严格证据关联、上下文长度限制和完整实验追踪下减少重复 Token。

**Architecture:** 新建无外部依赖的 `relation_batching.py` 负责证据规范化、重叠计算和严格分组；`TripletGenerator` 增加批量提示词、解析和持久化；`pipeline.py` 将检索与生成拆成两个阶段。`PipelineConfig` 和 Streamlit 暴露策略参数，单实体模式保留为论文基线。

**Tech Stack:** Python 3.10、unittest、OpenAI 兼容 API、Streamlit、现有 MySQL/Milvus 实验记录层。

---

### Task 1: 共享证据分组核心

**Files:**
- Create: `kg_extract_build/relation_batching.py`
- Create: `kg_extract_build/tests/test_relation_batching.py`

- [ ] **Step 1: 写失败测试**

```python
def test_build_relation_batches_requires_pairwise_overlap():
    evidence = {
        "A": hits(1, 2),
        "B": hits(1, 2, 3),
        "C": hits(3, 4),
        "D": hits(9),
    }
    batches = build_relation_batches(
        evidence, max_entities=3, min_overlap=0.4,
        max_context_chars=8000,
    )
    assert [item.entity_names for item in batches] == [
        ("A", "B"), ("C",), ("D",)
    ]

def test_batch_evidence_is_deduplicated_by_sentence_index():
    batch = make_relation_batch(...)
    assert [hit["sentence_index"] for hit in batch.evidence] == [1, 2, 3]
    assert batch.entity_evidence_ids["A"] == (1, 2)
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_relation_batching -v
```

Expected: FAIL，`kg_extract_build.relation_batching` 不存在。

- [ ] **Step 3: 实现最小分组模块**

```python
@dataclass(frozen=True)
class RelationBatch:
    entity_names: tuple[str, ...]
    evidence: tuple[dict, ...]
    entity_evidence_ids: dict[str, tuple[int, ...]]

def overlap_coefficient(left_ids, right_ids):
    denominator = min(len(left_ids), len(right_ids))
    return len(set(left_ids) & set(right_ids)) / denominator if denominator else 0.0

def build_relation_batches(entity_evidence, max_entities,
                           min_overlap, max_context_chars):
    # 按输入顺序贪心；候选必须与组内每个实体达到阈值；
    # 合并后的唯一证据字符数不得超过上限。
    ...
```

- [ ] **Step 4: 运行测试确认 GREEN**

Run: Task 1 的 unittest 命令。  
Expected: PASS。

- [ ] **Step 5: 中文提交**

```powershell
git add kg_extract_build/relation_batching.py kg_extract_build/tests/test_relation_batching.py
git commit -m "功能：新增共享证据实体分组"
```

### Task 2: 批量三元组生成

**Files:**
- Modify: `kg_extract_build/triplets.py`
- Create: `kg_extract_build/tests/test_triplet_batching.py`

- [ ] **Step 1: 写失败测试**

```python
def test_generate_batch_sends_unique_evidence_once_and_splits_by_head():
    result = generator.generate_batch(
        entities=[entity_a, entity_b],
        evidence=[hit_s1, hit_s2],
        entity_evidence_ids={"A": (1,), "B": (1, 2)},
    )
    assert completions.call_count == 1
    assert completions.prompt.count("[S1]") == 1
    assert result["A"][0]["head"] == "A"
    assert result["B"][0]["head"] == "B"
    assert recorder.call_ids_for_triplets == {1}
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_triplet_batching -v
```

Expected: FAIL，`generate_batch` 不存在。

- [ ] **Step 3: 实现批量提示词和解析**

```python
def generate_batch(self, entities, evidence, entity_evidence_ids,
                   batch_metadata=None):
    prompt = self._build_batch_prompt(
        entities, evidence, entity_evidence_ids
    )
    response = self.client.chat.completions.create(...)
    raw_items = self._load_json_array(response...)
    results = {}
    for entity in entities:
        entity_context = "\n".join(
            evidence_by_id[index] for index in entity_evidence_ids[name]
        )
        results[name] = self._validate_batch_items(
            raw_items, entity, entity_context
        )
    # 一条 llm_call，多实体 triplet 共享 source_llm_call_id。
    return results
```

- [ ] **Step 4: 测试失败记录和调试快照**

验证 API 异常不会返回伪成功空结果；错误信息脱敏；每个实体调试文件包含批次元数据和共享调用 ID。

- [ ] **Step 5: 运行测试确认 GREEN 并提交**

```powershell
git add kg_extract_build/triplets.py kg_extract_build/tests/test_triplet_batching.py
git commit -m "功能：支持共享证据批量三元组抽取"
```

### Task 3: Pipeline 两阶段编排

**Files:**
- Modify: `kg_extract_build/pipeline.py`
- Modify: `kg_extract_build/tests/test_pipeline_control.py`

- [ ] **Step 1: 写失败集成测试**

```python
def test_pipeline_retrieves_all_entities_before_first_batch_generation():
    timeline = []
    retriever.retrieve_with_details = lambda name: timeline.append(
        f"retrieve:{name}"
    ) or hits_for(name)
    generator.generate_batch = lambda *a, **k: timeline.append("generate") or {}
    run_pipeline(config, ...)
    assert timeline.index("generate") > timeline.index("retrieve:last")

def test_unrelated_entities_remain_single_entity_calls():
    # A/B 有共同 sentence_index，C 无共同证据。
    # A/B 调用一次 generate_batch，C 调用一次 generate。
    ...
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_pipeline_control -v
```

Expected: FAIL，当前仍是 retrieve 后立即 generate。

- [ ] **Step 3: 拆分检索和生成阶段**

```python
entity_evidence = {}
for entity in pending_entities:
    entity_evidence[name] = retrieve_entity_evidence(...)

batches = build_relation_batches(...)
for batch in batches:
    if len(batch.entity_names) == 1:
        raw_triplets[name] = generator.generate(entity, context)
    else:
        raw_triplets.update(generator.generate_batch(...))
```

缓存命中、无上下文、取消检查、事件指标和失败状态保持原有语义。

- [ ] **Step 4: 运行 Pipeline 测试和回归测试**

Run:

```powershell
D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_pipeline_control -v
```

Expected: PASS。

- [ ] **Step 5: 中文提交**

```powershell
git add kg_extract_build/pipeline.py kg_extract_build/tests/test_pipeline_control.py
git commit -m "功能：关系抽取改为先检索后分组"
```

### Task 4: 配置、快照和 Streamlit 参数

**Files:**
- Modify: `kg_extract_build/run_config.py`
- Modify: `kg_extract_build/dashboard_run.py`
- Modify: `kg_extract_build/tests/test_run_config.py`
- Modify: `kg_extract_build/tests/test_dashboard_run.py`

- [ ] **Step 1: 写失败测试**

```python
def test_relation_batch_defaults_are_effect_first():
    config = make_config()
    assert config.relation_strategy == "shared_context_batch"
    assert config.relation_batch_max_entities == 3
    assert config.relation_batch_min_overlap == 0.4
    assert config.relation_batch_max_context_chars == 8000

def test_relation_batch_parameters_are_in_sanitized_snapshot():
    snapshot = make_config().sanitized_snapshot()
    assert snapshot["relation_batch"]["max_entities"] == 3
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_run_config kg_extract_build.tests.test_dashboard_run -v
```

Expected: FAIL，配置字段不存在。

- [ ] **Step 3: 实现配置和校验**

```python
relation_strategy: str = "shared_context_batch"
relation_batch_max_entities: int = 3
relation_batch_min_overlap: float = 0.4
relation_batch_max_context_chars: int = 8000
```

校验策略枚举、实体数 `1..10`、阈值 `0..1`、上下文字符数 `1000..50000`。快照以 `relation_batch` 子对象保存。

- [ ] **Step 4: 增加 Streamlit 高级设置**

界面提供策略选择、最大实体数、重叠阈值和上下文字符数；选择 `single_entity` 时隐藏批量参数并显示基线说明。

- [ ] **Step 5: 运行测试并仅暂存本任务代码**

`run_config.py` 已有用户未提交的 ModelScope URL 修改。提交时生成仅包含本任务 hunks 的缓存补丁，禁止把该 URL 改动纳入提交。

```powershell
git commit -m "功能：可视化配置关系批量抽取策略"
```

### Task 5: 文档与最终验证

**Files:**
- Modify: `kg_extract_build/README.md`
- Modify: `kg_extract_build/agent.md`

- [ ] **Step 1: 更新中文文档**

说明两种策略、默认参数、分组公式、缓存行为、论文对照建议和批量调用持久化语义。

- [ ] **Step 2: 运行完整验证**

```powershell
D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest discover -s kg_extract_build/tests -p "test_*.py" -v
D:\ProgramData\anaconda3\envs\env_agent\python.exe -m compileall -q kg_extract_build
git diff --check
```

Expected: 所有测试通过、编译退出码 0、差异检查无错误。

- [ ] **Step 3: Streamlit 冒烟测试**

临时启动 `dashboard.py`，确认首页和 `/_stcore/health` 返回 HTTP 200，再关闭仅用于验收的进程。

- [ ] **Step 4: 审核 Git 边界**

确认 `.claude/`、实验输出目录和用户的 ModelScope URL 修改未进入本功能提交。

- [ ] **Step 5: 中文提交**

```powershell
git add kg_extract_build/README.md kg_extract_build/agent.md
git commit -m "文档：补充共享上下文关系抽取说明"
```
