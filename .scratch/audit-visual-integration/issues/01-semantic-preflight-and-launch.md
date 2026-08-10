# 01 — 语义审核预检与启动入口

**What to build:** 审核员在现有施工方案审核页面确认上下文后，可以确认声明规范和作业类型必备补充规范，查看版本、索引发布状态、覆盖缺口及外部能力状态，并在条件明确后启动已接入的语义审核。

**Blocked by:** None — can start immediately.

**Status:** completed

**Implementation:** Added visible normative scope inputs, dependency capability status, coverage warnings, and preserved the single primary launch action in `dashboard_audit.py`.

- [ ] 预检沿用现有页面结构和原生控件，显示规范范围、版本/年份、发布状态、覆盖缺口及受影响任务。
- [ ] 未覆盖或不可用状态以明确文本说明，不能渲染为通过或隐藏。
- [ ] 审核员可通过单一、可见的主操作启动全量审核；页面不显示密钥或敏感连接信息。
- [ ] Streamlit `AppTest` 验证正常预检、覆盖缺口和依赖不可用时的用户可见反馈。
