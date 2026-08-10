# 05 — 报告版本回读与人工更正 UI

**What to build:** 审核员在历史运行回读中可查看初稿、已发布报告和人工更正版本，并能从已发布版本填写更正原因创建新版本，同时在源快照变更时收到必须重新审核的提示。

**Blocked by:** 04 — 人工复核与首次正式报告发布 UI.

**Status:** completed

**Implementation:** Added report version table and published-report correction form with re-audit error feedback.

- [ ] 版本视图展示报告类型、版本号、创建/发布时间、操作者、变更原因及前序版本关联。
- [ ] 人工更正通过清晰表单创建新版本，不覆盖已发布版本或机器原始结果。
- [ ] 源方案、审核上下文或证据快照变更时禁用更正并显示重新审核原因。
- [ ] 已发布和更正版本均可回读其摘要及可用导出。
- [ ] `AppTest` 验证版本回读、更正创建、前序关联和重新审核门禁。
