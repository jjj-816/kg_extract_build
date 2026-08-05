# 规范条款向量索引 MVP 设计

## 目标

按 `docs/design/2026-07-24-source-aware-pipeline-and-normative-vector-index-design.md` V1.1 的验收标准，补齐当前项目缺失的"规范条款向量索引"半场，以 MVP 范围打通最小闭环：

规范文档登记 → 条款解析落库 → 长条款分段 → MiniLM 编码 → Milvus 集合族索引 → 发布版打包 → 纯向量检索预览。

MVP 只实现设计基线模型 `paraphrase-multilingual-MiniLM-L12-v2`，Qwen3-0.6B / BGE-M3 与多发布版管理留待后续。

## 背景缺口（本次要补的）

- `kg_normative_*` 8 张表已建（`schema.sql`），但**全库无写路径**，仅 `normative.py` 提供条款解析与版本过滤纯函数。
- 无规范向量索引页面；[dashboard.py:646-680](kg_extract_build/dashboard.py) 侧边栏只有总览/批次/文档/LLM/图谱/运行/审核/评估 8 页。
- 无规范专用 Milvus 集合族；[vector_store.py](kg_extract_build/vector_store.py) 只有 pipeline 用的单集合 `kg_document_segments`。
- 环境：`env_agent`（Python 3.11）已装 pymilvus 2.6.16、sentence-transformers 5.1.2；torch 为 CPU 版；Milvus 服务由用户在 Docker 中自行启动（URI `http://127.0.0.1:19530`）。

## 范围

### MVP 纳入

- 规范登记：`kg_normative_family/version` 写路径，元数据确认、替代关系，校验生效>失效、替代无环、`superseded/repealed` 未确认 `invalid_year` 禁止进入发布版。
- 条款落库：`kg_normative_clause_set/clause` 写路径；重解析生成新 `clause_set_id`，不覆盖历史条款（`ON DELETE RESTRICT` 已保证引用不可变）。
- 分段：长条款按模型 tokenizer 分段，加规范名/章节/条款号前缀，允许少量重叠，记录 `token_count`，不静默截断超长输入。
- 编码：MiniLM 384 维；冻结 `encoder_profile`（查询/文档模板前缀、池化、归一化、最大输入长度、模型文件指纹、维度）。
- Milvus 集合族：`kg_normative_clauses__minilm_384__v1` 命名；维度隔离；写入前校验维度。
- 索引构建/重建：幂等指纹（复用 [normative.py:134](kg_extract_build/normative.py) `build_index_fingerprint`）；状态机 pending→building→ready/failed；部分向量写入失败不得进入 ready；失败不影响三元组实验。
- 发布版最小支持：把已验证索引组成一个 `published` 发布版（`kg_normative_index_release` + `_member`），供检索预览选择。
- 纯向量检索预览：按审核年份计算候选版本、声明规范范围限制、覆盖状态四态、同年版本冲突标记、segment→clause 聚合去重、超额检索扩窗、不调 Neo4j 不调 LLM。
- 证据生命周期：删除实验批次前检查其文档是否被规范版本/条款集/发布版引用；被引用拒绝删除并提示归档。
- 配置：`KG_NORM_VECTOR_MODEL_PATH`、`KG_NORM_MILVUS_COLLECTION_PREFIX=kg_normative_clauses`、`KG_NORM_MILVUS_URI`。

### MVP 不纳入（后续）

- Qwen3-0.6B / BGE-M3 模型接入与 FP16 GPU 显存管理（`encoder_profile` 数据结构预留）。
- 多发布版管理 UI（MVP 仅"新建发布版=打包当前已验证索引"）。
- 正式审核冻结 `release_id` 与审核报告（属正式审核模块，原设计 §3.11 另行设计）。
- §16.8 检索效果完整报告（Recall/MRR/显存）。MVP 建 gold 固件 + MiniLM 基础检索断言。

## 架构

新增模块（沿用现有分层，`kg_extract_build/` 下）：

| 模块 | 职责 |
|---|---|
| `normative_meta.py` | 族/版本登记、元数据确认、替代关系与版本校验 |
| `normative_persistence.py` | 8 张 `kg_normative_*` 表写路径，事务提交 |
| `normative_segmentation.py` | 长条款 token 分段、前缀、重叠 |
| `normative_encoder.py` | sentence-transformers 封装，冻结 encoder_profile |
| `normative_vector_store.py` | Milvus 集合族封装、维度隔离 |
| `normative_indexer.py` | 构建/重建、幂等指纹、状态机 |
| `normative_search.py` | 纯向量检索预览、覆盖状态、聚合去重 |
| `dashboard_normative.py` | 规范向量索引页面（登记/索引管理/检索预览三区域） |

`settings.py` 增加 `KG_NORM_*` 配置读取；`.env.example` 补充对应项；`persistence.py` 删除流程增加规范引用预检查（修复"先删向量再删 SQL、FK 失败后批次卡死在 vectors_deleted_sql_pending"的现状隐患）。

## 数据流

```
规范文档(pipeline 产出 kg_document.source_type='spec')
  │ 登记区：自动提取候选 + 用户确认
  ▼
kg_normative_family / version（校验通过后落库）
  │ 条款解析：parse_normative_clauses（复用）
  ▼
kg_normative_clause_set（不可变）→ kg_normative_clause（完整条款+偏移+hash）
  │ 分段 + 编码
  ▼
segment（前缀、token_count）→ MiniLM embedding（冻结 encoder_profile）
  │ 写入集合族
  ▼
kg_normative_index（指纹幂等）→ kg_normative_index_segment（segment↔clause 映射）
  │ 打包
  ▼
kg_normative_index_release（published）+ member
  │ 检索预览
  ▼
MySQL 算 allowed_version_id（audit_year + 声明范围 + 同年冲突）→ 覆盖状态
→ 编码查询 → Milvus 超额检索 → 按 clause_id 聚合去重 → MySQL 回取完整条款
```

一致性原则：MySQL 是版本/有效年份/索引状态的唯一真实来源；Milvus 只存稳定标识（`index_id/family_id/version_id/clause_id/segment_id`）与向量，不独立判断有效性。

## 关键实现细节

### 集合族命名

```
f"{prefix}__{profile.slug}__v{profile.major}"
# 例：kg_normative_clauses__minilm_384__v1
```

不同模型、不同维度或不兼容索引版本使用不同物理集合；检索一次只选一个索引版本；不跨模型比较余弦分数；所有集合与 `kg_document_segments` 隔离。

### 幂等指纹

复用 `build_index_fingerprint`（document_content_hash + metadata_hash + clause_set_id + chunk_config + embedding_model_revision + encoder_profile_hash + embedding_dimension）。相同指纹不重复构建；重建产生新 `index_id`。

### 检索算法

- 初始 segment 窗口：`max(Top-K × 3, 30)`。
- 命中 segment 按 `clause_id` 聚合，每条款保留最高相似度；Top-K 表示条款数。
- 去重后不足 Top-K 时继续扩大窗口，直到足够条款、候选耗尽或达安全上限。
- 实际检索窗口、去重数量、停止原因写入 `retrieval_trace`。

### 覆盖状态

按每项声明规范返回 `covered` / `partial` / `uncovered` / `cited_but_unindexed`，语义遵循原设计 §12.3。

### 检索返回形状

遵循原设计 §18：`{coverage[], evidence[], retrieval_trace, warnings}`。evidence 含 `release_id/index_id/family_id/version_id/clause_set_id/clause_id/clause_number/text/clause_content_hash/score/rank/source_type/same_year_version_conflict/hit_segment_ids`。

## 错误处理与一致性

| 场景 | 处理 |
|---|---|
| 模型加载失败 | 索引 `failed` + `error_message`，不影响三元组实验 |
| 条款解析为空 | 构建失败并显示原因（区分回退与真为空） |
| Milvus 不可达 | 构建/检索报错并展示；不写 `ready`；旧索引继续服务检索 |
| 维度不匹配 | 写入前校验，拒绝写入 |
| 部分向量写入失败 | 索引不得进入 `ready`，保持 `building/failed`，可重建 |
| 删除被引用批次 | 先做规范引用预检查，被引用拒绝并提示归档；未引用走原流程 |
| 版本校验 | 生效>失效拒绝；替代成环拒绝；未确认 `invalid_year` 的 superseded/repealed 禁止进发布版；同年切换允许保存并自动产生冲突标记 |

## 测试设计

- `test_normative_meta.py`：版本校验、替代无环、未确认禁止发布、同年冲突。
- `test_normative_persistence.py`：8 表写路径、重解析不覆盖历史条款、不可变约束。
- `test_normative_segmentation.py`：长条款分段、前缀、重叠、token_count、不静默截断。
- `test_normative_search.py`：年份过滤、声明范围、覆盖四态、聚合去重、扩窗不足时继续扩展、同年冲突。
- `test_normative_vector_store.py`（mock pymilvus）：集合命名、维度隔离、指纹幂等跳过。
- `test_lifecycle_protection.py`：删除批次前规范引用检查。
- Gold 固件（原设计 §16.4）：`第二十条`~`第二十二条`、`5.1.2`、多自然段、Markdown 表格、无编号回退、超 MiniLM 128 token 长条款。
- 端到端冒烟（Milvus 运行前提）：pipeline 跑规范样本文档 → 登记 → 落库 → 编码 → 建索引 → 打包发布版 → 检索返回完整条款与覆盖状态。

## 里程碑

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M0 | 配置与 schema 就绪 | `.env.example` 有 `KG_NORM_*`；8 表可在目标库初始化 |
| M1 | 登记 + 条款落库 | 单测全过；重解析不覆盖历史条款有测试证明 |
| M2 | 分段 + MiniLM 编码 | 分段/编码单测过；encoder_profile 冻结断言 |
| M3 | Milvus 集合族 + 索引构建 | MiniLM 索引构建成功；指纹幂等重复构建跳过 |
| M4 | 发布版 + 检索逻辑 | gold 固件检索正确；覆盖状态四态有测试 |
| M5 | 检索预览页面 | 页面三区域可用；检索返回完整条款 |
| M6 | 生命周期保护 | 删除被引用批次被拒并有提示 |
| M7 | 端到端冒烟 | 真实 Milvus 下全链路跑通报告 |
