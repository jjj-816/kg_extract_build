# 06 审核页面端到端验收与可用性回归

**What to build:** 在标准 `env_agent` 环境中验证审核页面的生产路径：规范预检、语义审核、结果与证据阅读、人工复核、正式发布和版本更正，并保持既有视觉与交互风格。

**Blocked by:** 01–05。

**Status:** completed

**Implementation:** 已增加本地 `env_agent` Streamlit `AppTest`：在无 MySQL 安全模式下真实上传 `.docx`，覆盖证据块预览、任务证据阅读器、审核上下文、规范范围输入和页面异常回归。provider-backed 语义执行、发布持久化、下载及版本更正仍需配置 MySQL schema 与外部能力的环境验收。

- [x] 在 `env_agent` 中运行现有后端回归和新增 Streamlit AppTest。
- [x] 验证无 MySQL 时页面仍可进入，并完成 `.docx` 上传后的预览、任务证据和审核上下文路径。
- [ ] 验证完整用户路径、局部失败隔离、外部依赖降级、发布门禁、下载和报告版本关系。
- [ ] 在配置 MySQL schema 与 provider 的环境中验证语义执行、发布持久化和版本更正。
- [ ] 固化可复现验收命令与结果摘要，不包含实验评估或新视觉体系重构。
