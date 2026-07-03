# kg_extract_build Agent 指南

## 1. 项目定位

本目录实现一条面向页岩气工程文档的知识图谱抽取流水线。它从本地 `.txt` / `.md` 文档中抽取实体，进行实体去重与别名对齐，再结合 Schema 和相关上下文生成、校验关系三元组。

当前实现同时支持“抽取、调试、实验追踪和断点复用”。Neo4j 入库代码仍处于注释状态；启用 `KG_MYSQL_ENABLED=1` 后，最终三元组及其完整上游过程会写入 MySQL，检索句向量可选写入 Milvus。

## 2. 代码地图

| 文件 | 核心职责 |
| --- | --- |
| `pipeline.py` | 总入口，串联所有模块，管理文档级断点和调试缓存 |
| `settings.py` | 路径、LLM、本地向量模型及运行参数 |
| `documents.py` | 加载未处理文档，维护 `processed_docs.json` |
| `schema.py` | 加载并标准化实体/关系 Schema，校验关系方向和实体类型 |
| `extractor.py` | 长文分块，调用 LLM 抽取实体，补充规范名称实体 |
| `entity_aligner.py` | 实体去重、候选分组、向量相似度计算和 LLM 对齐 |
| `retriever.py` | 句子切分、向量编码和实体相关上下文检索 |
| `triplets.py` | 按实体生成三元组、读写实体级缓存、执行最终校验 |
| `persistence.py` | MySQL 实验仓储、内存测试仓储和文档级记录器 |
| `vector_store.py` | 可选 Milvus 切片向量存储 |
| `dashboard.py` | Streamlit 实验管理与知识图谱可视化后台 |
| `schema.sql` | MySQL 7 张实验数据表 |
| `__init__.py` | Python 包标识 |

## 3. 主流程

入口为 `pipeline.run_pipeline()`：

1. `KGSchema` 从 `kg_schema.json` 加载实体类型、关系类型及头尾类型约束；文件不存在时回退到 `kg_schema.example.json`。
2. `BreakpointManager` 读取 `processed_docs.json`，`DocumentLoader` 只返回尚未处理的 `.txt` 和 `.md` 文件。
3. 对每篇文档推断来源类型：文件名包含“规范”或“标准”时为 `spec`，否则为 `case`。
4. 优先读取 `shale_gas_entity_debug/<文档>/aligned_entities.json`。缓存不存在时：
   - `LongDocLLMEntityExtractor` 按最多 2000 字符分块并调用 LLM；
   - 通过正则额外识别《规范名称》及可能跟随的标准编号；
   - 过滤未在原文出现的 LLM 实体；
   - `EntityAligner` 结合规则、编辑距离、本地向量相似度和 LLM 完成别名对齐；
   - 保存原始实体与对齐结果。
5. `CorpusRetriever` 将全文按中文标点和换行切成句子，并使用本地 SentenceTransformer 模型编码。
6. 先对全部标准实体及其别名检索上下文，优先使用原文直接命中的句子，再补充向量相似句。
7. `relation_batching.py` 按共同 `sentence_index` 计算重叠系数；候选必须与组内每个实体达到阈值，并受实体数和去重上下文长度双重限制。
8. `TripletGenerator` 优先复用 `shale_gas_triplets_debug/<文档>/<实体>.json`；多实体批次共享一次 LLM 调用，无关实体继续单独调用。
9. 解析阶段按 head 将批量结果分回实体，再检查关系、尾实体长度、实体专属原文证据和 Schema 类型约束；必要时尝试调换头尾方向。
10. `TripletCorrector` 再次校验并去重。
11. 文档处理成功后写入 `processed_docs.json`。

简化数据流：

```text
文档
  -> 分块实体抽取
  -> 实体候选 [{name, type}]
  -> 实体对齐 [{name, type, aliases, source_type}]
  -> 全部实体相关句检索
  -> 共享证据严格分组与上下文去重
  -> 批量/单实体关系抽取
  -> 原始三元组
  -> Schema 校验
  -> (head, head_type, relation, tail, tail_type)
```

关系抽取配置保存在 `PipelineConfig`：

```python
relation_strategy = "shared_context_batch"  # 或 single_entity
relation_batch_max_entities = 3
relation_batch_min_overlap = 0.4
relation_batch_max_context_chars = 8000
```

批量模式不是固定凑满实体。没有共同证据或无法满足严格两两重叠的实体会形成单实体批次，并继续调用原有 `generate()`。多实体批次调用 `generate_batch()`；一条 `kg_llm_call` 可以作为同批多组原始三元组的 `source_llm_call_id`。

## 4. 核心数据结构

原始实体：

```python
{"name": "实体原文", "type": "Schema 中的实体类型"}
```

对齐后实体：

```python
{
    "name": "标准名称",
    "type": "实体类型",
    "aliases": ["标准名称", "别名"],
    "source_type": "spec"  # 或 case
}
```

LLM 三元组：

```python
{
    "head": "头实体",
    "head_type": "头实体类型",
    "relation": "Schema 中的关系",
    "tail": "尾实体",
    "tail_type": "尾实体类型"
}
```

最终校验结果为五元组列表：

```python
(head, head_type, relation, tail, tail_type)
```

## 5. 默认路径和配置

`settings.BASE_DIR` 是本目录的上一级，即 Git 仓库根目录。

| 配置 | 默认位置或值 |
| --- | --- |
| 输入文档 | `shale_gas_docs/guifan` |
| 主 Schema | `kg_schema.json` |
| 备用 Schema | `kg_schema.example.json` |
| 文档断点 | `processed_docs.json` |
| 实体调试缓存 | `shale_gas_entity_debug` |
| 三元组调试缓存 | `shale_gas_triplets_debug` |
| 向量模型 | `models/paraphrase-multilingual-MiniLM-L12-v2` |
| 检索句数 | `RETRIEVE_SENTENCE_NUM = 10` |
| 未知类型 | `未分类` |

LLM 通过以下环境变量配置：

- `LLM_API_KEY`
- `LLM_BASE_URL`，默认智谱 OpenAI 兼容接口
- `LLM_MODEL`，默认 `glm-4.5-air`

Neo4j 环境变量仍保留在配置中，但当前流程没有使用。

## 6. 运行方式

主要依赖：

```bash
pip install openai numpy sentence-transformers
```

从 Git 仓库根目录运行：

```bash
python -c "from kg_extract_build.pipeline import run_pipeline; run_pipeline()"
```

运行前确认：

- `LLM_API_KEY` 已设置；
- Schema JSON 可读取且结构正确；
- 本地向量模型目录存在；
- 输入文档使用 UTF-8；
- 运行账号对断点和两个调试目录具有写权限。

## 7. 缓存与重跑语义

项目有三层可复用状态：

1. `processed_docs.json`：文档级完成标记。命中后整篇文档不会加载。
2. `aligned_entities.json`：实体抽取和对齐缓存。命中后不会再次调用实体抽取/对齐模型。
3. `<实体>.json`：三元组缓存。命中后不会再次调用三元组抽取模型。

修改提示词、Schema、模型、阈值或对齐算法后，旧缓存不会自动失效。需要根据变更范围清理对应缓存：

- 完整重跑：备份后清理 `processed_docs.json`、对应实体缓存和三元组缓存；
- 只重做三元组：清理文档断点及对应三元组目录；
- 重做实体对齐：同时清理文档断点、实体缓存和三元组缓存。

不要只删除 `processed_docs.json` 后期待模型重新抽取；实体级和三元组级缓存仍会被复用。

## 8. Schema 约定

Schema 顶层包含：

```json
{
  "entity_types": [],
  "relation_types": []
}
```

实体类型可写成字符串，或带 `name`、`cn_name`、`description`、`examples` 的对象。关系类型对象还可使用：

```json
{
  "name": "关系名称",
  "head_types": ["允许的头类型"],
  "tail_types": ["允许的尾类型"]
}
```

关系名和已知实体类型必须与 Schema 精确匹配，否则会分别被丢弃或归一化为“未分类”。

## 9. 已知限制与风险

### 高优先级

- **数据库默认关闭。** 未设置 `KG_MYSQL_ENABLED=1` 时，最终结果仍只保留在内存和原有调试文件中。论文实验前必须确认 MySQL 已启用，并在后台看到对应 `run_id`。
- **无 Schema 时会抽不到三元组。** `KGSchema` 声称进入非约束模式，但 `render_allowed_relation_schema()` 在没有关系类型时返回“Return []”，提示词会要求模型输出空数组。
- **文件缓存没有版本信息。** 数据库运行会保存配置和 Schema 快照，但显式打开文件缓存复用后，仍可能混入旧模型结果。
- **三元组缓存文件名可能冲突。** 文档名和实体名只替换部分非法字符，不同名称清洗后可能映射到同一路径。

### 正确性与性能

- `extractor._split_document()` 在 Markdown 标题场景下可能把标题文本重复放入分块，需要通过单元测试确认和修正。
- `CorpusRetriever` 每处理一篇文档都会重新加载 SentenceTransformer；`EntityAligner` 还可能单独加载同一模型，耗时且占用双份内存。
- 检索器没有模型加载失败的降级路径；本地模型缺失会使整篇文档失败。
- `TripletGenerator` 在反向类型约束成立时会调换头尾但保留同一关系名；对非对称关系应确认这是否符合 Schema 语义。
- `TripletCorrector` 使用 `set` 去重，最终顺序不稳定。
- `os.listdir()` 未排序，文档处理顺序不稳定。
- 实体对齐的大候选组按名称分块，跨分块别名不会互相比较。
- `FREQ_THRESHOLD` 当前未被使用。
- `EXPERT_ENTITIES` 会无条件注入实体候选，即使实体未在原文出现；通常会因检索不到上下文而跳过三元组生成。

### 容错行为

- 单个 LLM 实体分块调用失败时返回空列表，其他分块继续。
- 单个三元组调用失败时返回空列表。
- 单篇文档发生未捕获异常时只打印错误，不写文档断点，下次可重试。
- “没有有效实体”会被视为处理完成并写入断点。
- `processed_docs.json` 损坏时初始化阶段会直接失败，目前没有容错恢复。

## 10. 修改原则

- 保持 LLM 输出为严格 JSON，并保留解析层的防御性校验；不要直接信任模型返回。
- 新增关系或实体类型时，同步更新 Schema 示例、提示词测试和方向约束测试。
- 改动缓存格式时增加显式版本字段，并兼容或清理旧缓存。
- 任何会影响抽取结果的配置都应纳入缓存指纹，例如 Schema 哈希、模型名、提示词版本和阈值。
- 在标记文档完成前，确保最终结果已原子化持久化。
- 不要将 API Key 写入源码、调试 JSON 或提交记录。
- 若恢复 Neo4j，使用上下文管理或明确的 `close()`，并设计重复运行时的幂等写入策略。

## 11. 建议测试

当前目录未附带测试。修改时至少覆盖：

1. 有/无 Markdown 标题的分块边界和字符完整性；
2. LLM 返回合法 JSON、代码围栏、说明文字和非法 JSON 的解析；
3. 实体名称必须存在于原文；
4. 通用实体不得与具体实体合并；
5. Schema 允许、拒绝及反向关系；
6. 直接命中优先于语义检索；
7. 缓存命中、损坏和版本失效；
8. 文件名清洗冲突；
9. 文档成功、失败和空实体时的断点行为；
10. 最终输出写入失败时不得标记文档完成。

建议先使用假的 OpenAI 客户端和假的向量模型做单元测试，避免测试依赖网络、真实密钥和大模型随机性。
