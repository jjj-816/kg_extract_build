# UI 工单逐项验收矩阵

本文件用于把 `.scratch/audit-visual-integration/issues` 中的要求与可复核证据绑定，避免仅依据工单 Status 判断完成。

## 已有证据

| 工单 | 要求范围 | 证据 | 结果 |
|---|---|---|---|
| 01 | 预检、规范范围、覆盖缺口、依赖状态、provider、单一启动入口 | `kg_extract_build/dashboard_audit.py` 的上下文预检与 provider 控件；`test_dashboard_audit.py`；live AppTest | 通过 |
| 02 | 阶段状态、完成/失败/降级统计、局部失败隔离 | `kg_extract_build/audit/ui_state.py`、`dashboard_audit.py`、`semantic_runtime.py`；live AppTest；全量回归 | 通过 |
| 03 | 结果类型筛选、文档/规范/图线索证据区分及降级提示 | `dashboard_audit.py` 的结果详情与 `split_evidence()`；`ui_state.py`；全量回归 | 实现已覆盖，需补专门 UI 可见性 AppTest |
| 04 | 人工复核、发布门禁、发布后 JSON/DOCX 下载 | `test_dashboard_audit_report_ui.py`：门禁、发布、两个下载控件；`report_service.py` | 通过 |
| 05 | 历史版本、人工更正、前序关联、重新审核门禁 | `dashboard_audit.py` 的历史/更正入口；`report_service.py`、`ui_state.py` 单元覆盖 | 实现已覆盖，需补专门版本历史 AppTest |
| 06 | 真实环境端到端回归 | `test_dashboard_audit_live.py`；提交 `4e0f7d1` | 通过 |

## 可复现命令

离线回归：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:KG_MYSQL_ENABLED='0'
$env:KG_NORM_MILVUS_ENABLED='0'
conda run -n env_agent python -m pytest kg_extract_build/tests -q
```

实时 UI 验收（要求 MySQL、Milvus、JSA、Neo4j 已启动）：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:AUDIT_LIVE_UI='1'
$env:KG_MYSQL_ENABLED='1'
$env:KG_NORM_MILVUS_ENABLED='1'
$env:LLM_PROVIDER='ollama'
$env:LLM_MODEL='qwen3:0.6b'
conda run -n env_agent python -m pytest kg_extract_build/tests/test_dashboard_audit_live.py -q -s
```

当前已记录结果：离线回归 `321 passed, 1 skipped, 51 subtests passed`；实时 UI `1 passed`。
