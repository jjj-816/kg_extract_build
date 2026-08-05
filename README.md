# kg_extract_build

施工方案审查知识图谱构建与论文实验管理项目。

- 核心代码：`kg_extract_build/`
- 使用说明：`kg_extract_build/README.md`
- MySQL 建表：`kg_extract_build/schema.sql`
- Streamlit 可视化控制台：`kg_extract_build/dashboard.py`

## 快速开始

```powershell
conda activate env_agent
cd D:\ProgramData\PythonProject\NLPTest\AgentTest\github_kg_extract_build
python -m streamlit run kg_extract_build/dashboard.py
```

只需启动 Streamlit，在"运行实验"页面选择路径、文件、提供商、模型和切片长度即可完成一次实验。无需再单独执行 `pipeline.py` 脚本。

## 环境配置

首次使用前，将 `kg_extract_build/.env.example` 复制为 `kg_extract_build/.env`，并填写：

- 所选 LLM 提供商的 API Key（智谱 `ZAI_API_KEY`、DeepSeek `DEEPSEEK_API_KEY`、阿里云百炼 `DASHSCOPE_API_KEY` 等）
- MySQL 和 Milvus 连接信息（可选，不影响本地运行）
- 本地模型路径

API Key 优先从 `.env` 环境变量读取，也可在 Streamlit 界面中临时覆盖（仅当前会话有效，不会持久化到数据库）。

## 命令行模式（兼容保留）

```bash
pip install -r kg_extract_build/requirements.txt
python -m kg_extract_build.init_storage
python -c "from kg_extract_build.pipeline import run_pipeline; run_pipeline()"
```

## Neo4j 知识图谱同步

在 `.env` 中启用 MySQL 实验存储，并配置本地 Neo4j：

```env
KG_MYSQL_ENABLED=1
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=你的Neo4j密码
NEO4J_DATABASE=neo4j
```

在 Streamlit 的“知识图谱”页面展开“Neo4j 图谱发布”，选择已完成的运行批次后手动同步。系统仅导入有效的 `final` 三元组：实体以“实体类型 + 规范化名称”合并；每个关系断言保留运行、文档、LLM 调用和证据句快照；同一实体对的聚合关系使用 Schema 关系名作为 Neo4j 关系类型。

```cypher
MATCH (h:Entity)-[r:USES_EQUIPMENT]->(t:Entity)
RETURN h.name, t.name, r.assertion_count, r.document_count;

MATCH (h:Entity)-[:HAS_ASSERTION]->(a:RelationAssertion)-[:OBJECT]->(t:Entity)
RETURN h.name, a.relation_type, t.name, a.evidence_json, a.run_id;
```

## 规范向量索引

规范证据检索链路：将规范文档登记为版本 → 解析条款 → 按 token 分段 → MiniLM（`paraphrase-multilingual-MiniLM-L12-v2`，384 维）编码 → 写入 Milvus → 构建幂等索引与不可变发布版 → 按“规范条款向量”纯向量检索（审核年份过滤 + 覆盖状态 + 去重扩窗 + 完整条款回取）。MySQL 保存版本/条款集/索引/发布版元数据（唯一真实来源），Milvus 只存稳定标识与向量。

在 `.env` 中启用（需自行启动 Milvus 服务，默认 `http://127.0.0.1:19530`）：

```env
KG_NORM_MILVUS_ENABLED=1
KG_NORM_VECTOR_MODEL_PATH=D:\...\models\paraphrase-multilingual-MiniLM-L12-v2
KG_NORM_MILVUS_URI=http://127.0.0.1:19530
KG_NORM_MILVUS_COLLECTION_PREFIX=kg_normative_clauses
KG_NORM_MILVUS_TOKEN=
```

配置项：

- `KG_NORM_VECTOR_MODEL_PATH`：MiniLM 模型目录；缺省回退 `KG_VECTOR_MODEL_PATH`。
- `KG_NORM_MILVUS_URI` / `KG_NORM_MILVUS_TOKEN`：Milvus 连接，默认 `http://127.0.0.1:19530` / 空。
- `KG_NORM_MILVUS_COLLECTION_PREFIX`：集合族前缀，默认 `kg_normative_clauses`。
- `KG_NORM_MILVUS_ENABLED`：是否启用规范向量索引；未启用时页面仅提示、检索预览不可用。

Streamlit 侧边栏新增“规范向量索引”页面，三个区域：①规范登记——选择 `source_type='spec'` 且已完成的文档，确认名称/生效年份/状态后登记并解析条款；②索引管理——构建/重建幂等索引、创建发布版；③检索预览——输入查询 + 审核年份 + 发布版 + Top-K，渲染 evidence 与覆盖状态。

端到端冒烟（需 Milvus 服务与 MiniLM 模型就位、MySQL 已建表）：

```bash
python -m kg_extract_build.scripts.normative_smoke
```

预期输出 `build_index: {'status': 'ready', ...}` 与 `evidence count: 1`。
