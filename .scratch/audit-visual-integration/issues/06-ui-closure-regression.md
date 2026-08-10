# 06 — 审核页面端到端验收与可用性回归

**What to build:** 部署方可以在标准 `env_agent` 环境中验证整个审核页面的生产路径：规范预检、语义审核、结果与证据阅读、人工复核、正式发布和版本更正，且页面保持既有视觉与交互风格。

**Blocked by:** 01 — 语义审核预检与启动入口; 02 — 语义审核执行反馈与任务状态; 03 — 全量审核结果与分类型证据阅读; 04 — 人工复核与首次正式报告发布 UI; 05 — 报告版本回读与人工更正 UI.

**Status:** in-progress

**Implementation:** Core page paths and regression coverage are in place; full AppTest coverage of provider-backed semantic execution and publish persistence remains.

- [ ] 在 `env_agent` 中运行现有后端回归和新增 Streamlit `AppTest` UI 回归。
- [ ] 验证完整用户路径、局部失败隔离、外部依赖降级、发布门禁、下载和报告版本关系。
- [ ] 验证无 MySQL 或外部能力不可用时页面安全可用，已有运行可继续回读。
- [ ] 视觉检查确认沿用标题、分区、tabs、expander、dataframe 和状态消息的既有页面语言；长文本和错误提示可读，状态不只依赖颜色。
- [ ] 产出可复现验收命令和结果摘要，不包含实验评估或新视觉体系重构。
