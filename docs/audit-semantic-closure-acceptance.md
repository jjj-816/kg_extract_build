# 审核语义闭环验收

## 环境

使用 Conda `env_agent`。Milvus 是可选外部服务；离线回归显式关闭它，避免本机 `.env` 中的服务开关影响默认配置测试。

## 命令

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:KG_NORM_MILVUS_ENABLED='0'
conda run -n env_agent python -m pytest kg_extract_build/tests -q
```

生产闭环最小验收：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:KG_NORM_MILVUS_ENABLED='0'
conda run -n env_agent python -m pytest `
  kg_extract_build/tests/test_production_closure.py `
  kg_extract_build/tests/test_report_service.py `
  kg_extract_build/tests/test_compliance_runtime.py `
  kg_extract_build/tests/test_reasonableness.py `
  kg_extract_build/tests/test_bounded_graph.py `
  kg_extract_build/tests/test_normative_scope.py -q
```

## 验收边界

- 规范范围冻结为声明规范与作业类型补充规范；覆盖不足、未发布、未确认适用和同年冲突阻止合规结论。
- 文档证据、规范条款证据和图线索使用不同证据类型；图线索不能生成规范不符合结论。
- 语义模型结构化输出最多纠正一次；再次失败只隔离当前任务。
- 图服务失败降级为信息不足或人工复核；图查询限制关系白名单和最多两跳。
- 人工必办项未处理时禁止发布；发布和更正均保存不可变报告快照，JSON/DOCX 从同一快照导出。
- 本回归不启用 Gold 集、缺陷注入、A/B 对比或方法对比实验。
