# 01 — 语义审核运行时与证据包基础

**What to build:** 审核员启动语义审核时，系统能为每个语义审核项冻结文档证据、规范证据和图检索线索，并以统一的可替换能力端口执行任务。单个语义任务失败必须保留为系统审核失败，且不影响其他任务继续执行。

**Blocked by:** None — can start immediately.

**Status:** completed

**Implementation:** `semantic_runtime.py` and the `AuditOrchestrator` seam are implemented and covered by contract tests.

- [ ] 语义审核项在执行前形成可追溯、不可被模型扩充的证据包，并随运行快照保存。
- [ ] 外部规范检索、图检索和结构化审核能力可替换；任务结果保持现有统一状态与问题语义。
- [ ] 非法结构化结果至多触发一次受控纠正；再次失败仅隔离当前任务。
- [ ] 通过 `AuditOrchestrator` seam 验证证据冻结、结果校验和局部失败隔离。
