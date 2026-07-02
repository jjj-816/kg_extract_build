# kg_extract_build

页岩气工程知识图谱抽取与构建流程代码整理目录。

本目录从 `kgc4_modules_align` 中提取当前 `pipeline.py` 实际运行链路所需的代码，去掉了备份文件、`__pycache__` 和当前已注释的 Neo4j 导入模块，便于后续维护和复用。

## 目录内容

| 文件 | 作用 |
| --- | --- |
| `pipeline.py` | 主流程入口，串联文档读取、实体抽取、实体对齐、上下文检索、三元组抽取与校验 |
| `documents.py` | 文档加载与断点记录 |
| `extractor.py` | 长文档分块实体抽取 |
| `entity_aligner.py` | 实体去重、候选聚合与 LLM 辅助对齐 |
| `retriever.py` | 基于本地向量模型的实体上下文检索 |
| `triplets.py` | 三元组生成、缓存读取与结果校验 |
| `schema.py` | 图谱 schema 加载、渲染与类型/关系约束校验 |
| `settings.py` | 路径、模型、LLM、断点与调试输出配置 |
| `__init__.py` | Python 包标记文件 |

## 依赖

主要 Python 依赖：

```bash
pip install openai numpy sentence-transformers
```

如果后续恢复 Neo4j 入库，还需要额外安装：

```bash
pip install neo4j
```

## 输入与输出路径

`settings.py` 中的 `BASE_DIR` 指向本目录的上一级，也就是 Git 仓库根目录。因此默认路径如下：

| 配置项 | 默认路径 | 说明 |
| --- | --- | --- |
| `DOCUMENT_FOLDER` | `shale_gas_docs/guifan` | 待处理 `.txt` / `.md` 文档 |
| `SCHEMA_PATH` | `kg_schema.json` | 优先读取的图谱 schema |
| `SCHEMA_EXAMPLE_PATH` | `kg_schema.example.json` | schema 兜底文件 |
| `PROCESSED_RECORD` | `processed_docs.json` | 已处理文档断点记录 |
| `DEBUG_DIR` | `shale_gas_triplets_debug` | 三元组抽取调试输出 |
| `ENTITY_DEBUG_DIR` | `shale_gas_entity_debug` | 实体抽取与对齐调试输出 |
| `VECTOR_MODEL_PATH` | `models/paraphrase-multilingual-MiniLM-L12-v2` | 本地句向量模型 |

这些路径均可通过 `.env.example` 中对应的 `KG_*_PATH` 或目录环境变量覆盖。

## 环境变量

LLM 配置可通过环境变量覆盖：

```bash
set LLM_API_KEY=your_api_key
set LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
set LLM_MODEL=glm-4.5-air
```

PowerShell 示例：

```powershell
$env:LLM_API_KEY="your_api_key"
$env:LLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4/"
$env:LLM_MODEL="glm-4.5-air"
```

## 运行方式

在项目根目录执行：

```bash
python -c "from kg_extract_build.pipeline import run_pipeline; run_pipeline()"
```

流程会自动跳过 `processed_docs.json` 中已处理的文档。若需要重新处理全部文档，可以先备份并删除该断点文件。

## 流程说明

1. 加载 schema：读取 `kg_schema.json`，没有时回退到 `kg_schema.example.json`。
2. 加载文档：从 `shale_gas_docs/guifan` 读取未处理的 `.txt` / `.md` 文件。
3. 实体抽取：对长文档分块，调用 LLM 抽取专业实体。
4. 实体对齐：结合规则、向量相似度和 LLM 判断，将别名对齐到标准实体。
5. 上下文检索：为每个实体检索相关句子，作为三元组抽取上下文。
6. 三元组抽取：按 schema 约束调用 LLM 生成关系三元组，并保存调试结果。
7. 三元组校验：过滤非法关系和类型不匹配结果。
8. 断点更新：文档处理完成后写入 `processed_docs.json`。

## 维护备注

- 当前目录只包含主流程实际用到的代码；原目录中的 `*_backup.py`、`__pycache__` 未迁移。
- `neo4j_builder.py` 当前未迁移，因为 `pipeline.py` 中 Neo4j 相关代码处于注释状态。
- 调试缓存会优先复用已保存的实体对齐结果和三元组结果。如需强制重新抽取，可清理对应文档在 `shale_gas_entity_debug` 和 `shale_gas_triplets_debug` 下的缓存。

## 实验数据库与可视化后台

为论文实验复现，流程现在可将完整执行数据写入 MySQL，并将检索句向量同步到 Milvus。默认仍处于关闭状态，未配置数据库时原流程可以继续运行。

### 1. 安装新增依赖

```bash
pip install -r kg_extract_build/requirements.txt
```

### 2. 创建 MySQL 数据库

先创建空数据库：

```sql
CREATE DATABASE kg_experiments
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

将本目录的 `.env.example` 复制为 `.env`，再填写连接信息。设置 `KG_MYSQL_ENABLED=1` 后，流程默认会自动执行 `schema.sql` 建表；也可以手工执行该 SQL，并设置 `KG_MYSQL_AUTO_INIT=0`。

配置好环境变量后，也可以一条命令创建数据库并建表：

```bash
python -m kg_extract_build.init_storage
```

MySQL 保存：

- 实验批次、配置与 Schema 快照；
- 文档原文与哈希；
- 实体抽取块和检索句切片；
- 每次 LLM 的 Prompt、原始响应、解析结果、耗时和错误；
- 原始实体、对齐实体和别名；
- 检索命中、相似度和匹配方式；
- 原始三元组与最终校验三元组。

### 3. 配置 Milvus

设置：

```text
KG_MILVUS_ENABLED=1
KG_MILVUS_URI=http://127.0.0.1:19530
KG_MILVUS_TOKEN=
KG_MILVUS_COLLECTION=kg_document_segments
```

Milvus 只保存 `retrieval_sentence` 的向量。其主键直接使用 MySQL 的 `chunk_id`，因此启用 Milvus 时必须同时启用 MySQL。集合在第一次写入时按实际向量维度自动创建。

### 4. 论文实验建议

每次运行都会创建新的 `run_id`。默认配置不会复用旧断点和文件缓存：

```text
KG_RESPECT_LEGACY_BREAKPOINT=0
KG_REUSE_ENTITY_CACHE=0
KG_REUSE_TRIPLET_CACHE=0
```

这能保证每次实验完整记录真实调用过程。需要调试续跑时可显式打开对应开关，并在论文记录中注明缓存策略。

### 5. 启动管理后台

从项目根目录执行：

```bash
python -m streamlit run kg_extract_build/dashboard.py
```

后台包含实验总览、实验批次、文档追踪、LLM 调用和知识图谱五个页面。MySQL 密码既可通过环境变量提供，也可只在后台侧边栏临时输入。
