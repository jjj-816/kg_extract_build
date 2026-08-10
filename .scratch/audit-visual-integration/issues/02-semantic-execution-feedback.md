# 02 — 语义审核执行反馈与任务状态

**What to build:** 审核员启动审核后，可在当前审核页面看到合规与合理性语义任务的实际执行反馈、任务级完成状态、局部失败和图服务降级原因，不再看到“等待后续能力接入”的过时提示。

**Blocked by:** 01 — 语义审核预检与启动入口.

**Status:** completed

**Implementation:** Added task execution counters and explicit pending/system-failure/degradation messaging to the existing result area; stale waiting wording is removed.

- [ ] 审核执行区展示阶段、已完成任务、失败任务和降级任务的可读状态。
- [ ] 4 个语义合规任务和 6 个语义合理性任务显示实际执行结果或明确失败/降级原因。
- [ ] 单任务失败、规范覆盖不足或图服务不可用不会中断其余任务的页面结果。
- [ ] `AppTest` 在受控外部能力下验证正常执行、局部失败隔离和图服务降级。
