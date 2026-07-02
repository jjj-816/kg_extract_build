# kg_extract_build

施工方案审查知识图谱构建与论文实验管理项目。

- 核心代码：`kg_extract_build/`
- 使用说明：`kg_extract_build/README.md`
- MySQL 建表：`kg_extract_build/schema.sql`
- Streamlit 后台：`kg_extract_build/dashboard.py`

快速开始：

```bash
pip install -r kg_extract_build/requirements.txt
python -m kg_extract_build.init_storage
python -c "from kg_extract_build.pipeline import run_pipeline; run_pipeline()"
python -m streamlit run kg_extract_build/dashboard.py
```

首次使用前，将 `kg_extract_build/.env.example` 复制为
`kg_extract_build/.env` 并填写 MySQL、Milvus、LLM 和本地模型路径。
