# 审核页面 UI 集成验收记录

## 本地安全回归

在仓库根目录执行：

```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:KG_MYSQL_ENABLED = "0"
$env:KG_NORM_MILVUS_ENABLED = "0"
conda run -n env_agent python -m pytest kg_extract_build/tests -q
```

当前基线：`317 passed, 51 subtests passed`。

其中 `kg_extract_build/tests/test_dashboard_audit.py` 使用内存生成的 `.docx` 走 Streamlit `AppTest`，覆盖：

- 无 MySQL 时审核页面仍可进入；
- `.docx` 上传和结构化证据预览；
- 任务证据阅读器和审核上下文 tabs；
- 声明规范、补充规范输入；
- 页面无未捕获异常。

## 真实依赖环境验收

以下步骤必须在配置好 MySQL schema、规范检索、图检索以及语义模型 provider 的环境执行；本地安全模式不等价于该验收：

1. 用 `KG_MYSQL_ENABLED=1` 启动页面，确认 schema health 通过。
2. 上传方案，填写项目、作业目的、作业类型确认、声明规范和补充规范。
3. 点击唯一的审核启动动作，确认 4 个合规任务和 6 个合理性任务出现实际执行状态。
4. 人工处置所有 mandatory review，确认未完成前发布按钮保持门禁。
5. 发布正式报告，下载同一快照的 JSON 和 DOCX。
6. 在历史版本中创建更正版本，确认原版本不被覆盖；改变 source snapshot 时必须触发重新审核门禁。

## 当前限制

页面没有内置 provider 模拟器或本地伪造数据库，因此上述真实依赖链路不能由无 MySQL AppTest 证明。当前工单 06 保持 `in-progress`，直到依赖环境验收结果可复现并纳入测试记录。
