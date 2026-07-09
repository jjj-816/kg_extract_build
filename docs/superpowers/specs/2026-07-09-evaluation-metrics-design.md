# 实验评估指标模块设计

日期：2026-07-09

## 背景

当前知识图谱构建流程已经可以把实验批次、文档、实体、检索证据、LLM 调用和最终三元组写入 MySQL。下一阶段需要通过人工标注数据评价不同实验方法的效果，用于论文实验对比。

人工标注数据以三元组 JSON 文件夹形式提供，结构尽量兼容当前 `shale_gas_triplets_debug`。评估页面允许选择一个历史实验记录，再选择或输入一个人工标注文件夹路径，系统加载两侧三元组并计算指标，最终把评估结果持久化保存。

## 目标

1. 在 Streamlit 中增加“实验评估”能力。
2. 支持选择历史实验记录 `run_id`。
3. 支持选择本机人工标注文件夹，并预览匹配情况。
4. 支持计算并展示以下指标：
   - Entity Precision / Recall / F1
   - Relation Precision / Recall / F1
   - Triplet Precision / Recall / F1
   - Invalid Relation Rate
   - Hallucination Rate，也可在论文中表述为 Unsupported Triplet Rate
   - Evidence Coverage
5. 支持把每次评估结果保存到 MySQL，便于后续可视化和论文实验复现。
6. 支持识别“同一实验 + 同一标注内容”是否已经评估过，并在界面中提示历史评估记录。

## 非目标

1. 第一版不做语义相似匹配。
2. 第一版不调用 LLM 判断幻觉或证据充分性。
3. 第一版不做人工标注编辑器，只读取用户已经准备好的标注文件夹。
4. 第一版不删除或覆盖已有评估记录；重新计算会保存为新的评估记录。

## 标注数据格式

人工标注文件夹推荐结构：

```text
gold_annotations/
  文档A/
    实体1.json
    实体2.json
  文档B/
    实体1.json
```

每个 JSON 文件支持两种格式。

兼容 debug 文件格式：

```json
{
  "entity": "高处",
  "triplets": [
    {
      "head": "《高处作业分级》GB/T 3608-2008",
      "head_type": "规范条款",
      "relation": "REGULATES",
      "tail": "高处",
      "tail_type": "作业活动"
    }
  ]
}
```

简化数组格式：

```json
[
  {
    "head": "《高处作业分级》GB/T 3608-2008",
    "head_type": "规范条款",
    "relation": "REGULATES",
    "tail": "高处",
    "tail_type": "作业活动"
  }
]
```

加载时会跳过无法解析的文件，并在预览或结果详情中显示错误列表。

## 匹配与规范化规则

第一版默认采用严格匹配，保证论文指标可解释、可复现。

三元组规范化字段：

```text
head + head_type + relation + tail + tail_type
```

规范化处理包括：

1. 去除字段首尾空白。
2. relation 使用现有 schema 规范化逻辑。
3. entity_type 使用现有 schema 规范化逻辑。
4. 保留原始实体名称，不默认做别名合并。

Entity 指标从三元组中抽取实体集合：

```text
(head, head_type)
(tail, tail_type)
```

Relation 指标使用关系边集合：

```text
(head, relation, tail)
```

Triplet 指标使用完整五元组集合：

```text
(head, head_type, relation, tail, tail_type)
```

## 指标定义

Precision / Recall / F1 统一按照集合匹配计算：

```text
TP = model_set ∩ gold_set
FP = model_set - gold_set
FN = gold_set - model_set
Precision = TP / (TP + FP)
Recall = TP / (TP + FN)
F1 = 2 * Precision * Recall / (Precision + Recall)
```

当分母为 0 时：

1. model 和 gold 都为空，Precision、Recall、F1 记为 1.0。
2. model 非空但 gold 为空，Precision 记为 0.0，Recall 记为 1.0，F1 记为 0.0。
3. model 为空但 gold 非空，Precision 记为 1.0，Recall 记为 0.0，F1 记为 0.0。

Invalid Relation Rate：

```text
非法关系三元组数 / 模型输出三元组总数
```

非法关系判断使用当前 `kg_schema.json`：relation 不存在，或 head_type、relation、tail_type 组合不被允许，均视为非法。

Hallucination Rate / Unsupported Triplet Rate：

```text
疑似无支持三元组数 / 模型输出三元组总数
```

第一版采用规则判断：如果 tail 不在文档原文中，也不在该三元组关联的检索证据或 LLM context 中，则视为疑似无支持。head 可作为辅助判断，但不作为唯一依据，因为 head 可能是规范名称、条款名称或标准化实体。

Evidence Coverage：

```text
有证据覆盖的三元组数 / 模型输出三元组总数
```

第一版证据覆盖判断：三元组的 tail 出现在检索证据句或 LLM context 中，即认为有证据覆盖。后续可以扩展为 head/tail 双实体覆盖、证据句编号覆盖或人工证据标注覆盖。

## 数据来源

模型输出优先从 MySQL 读取：

1. `kg_experiment_run`：历史实验记录。
2. `kg_document`：实验文档、文件名、原文内容。
3. `kg_triplet`：`stage='final'` 的最终三元组。
4. `kg_retrieval_result`：实体检索证据。
5. `kg_llm_call`：必要时读取 context 或 metadata 辅助证据覆盖判断。

如果某些旧实验没有 MySQL 记录，后续可以增加从 `shale_gas_triplets_debug` 读取模型输出的兼容入口；第一版以 MySQL 历史实验为主。

## 预览匹配情况

用户选择历史实验和标注文件夹后，页面显示：

1. 历史实验文档数。
2. 标注文件夹文档数。
3. 成功匹配文档数。
4. 缺失标注的实验文档。
5. 标注中多出的文档。
6. gold 三元组数量。
7. model 三元组数量。
8. 解析错误文件数量和列表。
9. 已存在评估记录数量。

匹配文档默认使用文档目录名和 `kg_document.file_name` 的 stem 匹配。例如 `高处作业.md` 可匹配标注目录 `高处作业/`。

## 已评估记录处理

系统会对人工标注文件夹内容计算 `gold_hash`。判断是否已经评估过时使用：

```text
run_id + gold_hash
```

不使用 `gold_path` 作为唯一依据，因为同一路径下的人工标注内容可能被修改。

如果同一 `run_id + gold_hash` 已存在评估记录，预览页面仍然展示完整匹配情况，并额外列出历史评估记录：

1. 评估时间。
2. gold_hash。
3. 匹配文档数。
4. Triplet F1。
5. 查看结果操作。

界面提供两个操作：

1. 查看已有评估结果。
2. 重新计算并保存为新评估记录。

## MySQL 持久化设计

新增表 `kg_evaluation_run`：

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
```

新增表 `kg_evaluation_metric`：

```sql
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

`kg_evaluation_run.summary_json` 保存总体摘要，`kg_evaluation_metric.details_json` 保存 TP、FP、FN 示例、疑似幻觉三元组和无证据三元组示例。

## 模块划分

新增 `kg_extract_build/evaluation.py`：

1. 加载 gold 标注文件夹。
2. 计算 gold_hash。
3. 规范化三元组。
4. 计算 Entity / Relation / Triplet 指标。
5. 计算 Invalid Relation Rate。
6. 计算 Hallucination Rate。
7. 计算 Evidence Coverage。
8. 输出可序列化的评估结果对象。

扩展 `kg_extract_build/persistence.py`：

1. 查询历史实验。
2. 查询实验文档和最终三元组。
3. 查询已有评估记录。
4. 保存评估运行和指标明细。

扩展 `kg_extract_build/dashboard.py` 或新增页面模块：

1. 增加“实验评估”页面。
2. 提供历史实验选择框。
3. 提供标注文件夹路径输入。
4. 展示预览匹配情况。
5. 展示已有评估记录。
6. 计算、展示并保存新评估结果。

## 错误处理

1. MySQL 未连接时，评估页面提示需要先启用 MySQL。
2. 标注路径不存在时，阻止计算并提示路径错误。
3. 标注 JSON 解析失败时，不中断整个评估；记录错误并在预览中展示。
4. 历史实验没有最终三元组时，允许预览，但计算时提示该实验无可评估模型输出。
5. schema 文件缺失或解析失败时，禁用 Invalid Relation Rate，并在结果中记录原因。

## 测试计划

1. gold 文件夹加载测试：兼容对象格式和数组格式。
2. gold_hash 测试：同内容同 hash，内容变化 hash 改变。
3. 严格三元组匹配测试。
4. Entity / Relation / Triplet P/R/F1 边界测试。
5. Invalid Relation Rate 测试。
6. Evidence Coverage 和 Hallucination Rate 规则测试。
7. MySQL schema 测试：新增评估表包含必要字段和索引。
8. Streamlit smoke 测试：没有 MySQL 连接时页面可正常渲染提示。

## 第一版交付边界

第一版完成后，用户可以在界面中选择一个历史实验，输入人工标注文件夹路径，看到匹配预览，计算上述指标，并把结果保存到 MySQL。结果页面至少包含总体指标、按文档指标、错误样例和历史评估记录。
