# 04 — 受限图检索与图线索回溯

**What to build:** 审核员可为合理性审核取得来自已确认正确历史案例的工程知识线索。每条线索均可回溯到关系断言和原始证据句，并受任务关系白名单与两跳路径上限限制；图服务不可用时系统明确降级。

**Blocked by:** 01 — 语义审核运行时与证据包基础.

**Status:** completed

**Implementation:** `bounded_graph.py` enforces read-only retrieval, relationship allowlists, a two-hop limit, provenance, and degradation.

- [ ] 图检索只读访问已确认正确的历史案例，并返回关系断言、来源文档身份和证据句。
- [ ] 查询遵守任务关系白名单和最多两跳的路径上限，聚合关系不脱离断言单独使用。
- [ ] 图检索失败或无线索时生成可读的降级信息，不伪装为方案结论。
- [ ] 生产审核不实施同源屏蔽；论文实验的跨格式来源映射与同源屏蔽不在本工单范围内。
- [ ] 契约测试覆盖路径限制、来源回溯和不可用降级。
