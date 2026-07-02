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
