# 03 — 规范向量合规审核闭环

**What to build:** 审核员执行一份已确认上下文的施工方案时，4 个语义合规审核项可从已发布规范条款集中定位候选、判断适用性、引用完整条款和方案原文形成可复核结论，并进入智能审核初稿。

**Blocked by:** 01 — 语义审核运行时与证据包基础; 02 — 规范范围确认与覆盖预检.

**Status:** completed

**Implementation:** `ComplianceRuntime` and normative evidence gates are connected to `AuditOrchestrator` through an injectable runtime.

- [ ] 仅已发布规范索引发布版中的完整条款可进入合规审核证据包。
- [ ] 适用性与合规性分步执行，并处理审核基准年份、作业条件和版本冲突。
- [ ] 每个不符合结论同时引用方案文档证据和已确认适用的完整规范证据。
- [ ] 4 个语义合规任务的候选、适用性、结论和失败/降级原因在初稿中可查。
- [ ] 使用可替换检索和模型实现完成端到端审核行为测试。
