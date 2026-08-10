# 05 — 图增强合理性审核闭环

**What to build:** 审核员运行完整审核时，6 个语义合理性审核项可使用受限图检索线索形成工程风险提示、信息不足或待专家复核结论；必要时可进行一次受控的二次规范候选检索。

**Blocked by:** 01 — 语义审核运行时与证据包基础; 03 — 规范向量合规审核闭环; 04 — 受限图检索与图线索回溯.

**Status:** completed

**Implementation:** `ReasonablenessRuntime` is connected to `AuditOrchestrator`; graph clues remain engineering-review evidence and secondary normative search is capped at one call.

- [ ] 6 个语义合理性任务不再停留在“等待后续阶段执行”状态。
- [ ] 图线索和规范证据以不同证据类型进入结果与报告；图线索不能支撑确定性规范不符合。
- [ ] 图线索不足或图服务不可用时，任务输出信息不足或待专家复核，并保留原因。
- [ ] 二次规范候选检索最多一次，且不改变规范证据准入与结论校验规则。
- [ ] 通过完整审核 seam 验证合理性任务结果及与合规任务的隔离。
