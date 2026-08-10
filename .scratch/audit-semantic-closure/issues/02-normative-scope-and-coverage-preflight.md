# 02 — 规范范围确认与覆盖预检

**What to build:** 审核员可在执行前确认方案声明规范，并为已选作业类型登记必备补充规范；系统展示规范版本、审核基准年份、索引发布状态和规范库覆盖缺口，从而阻止不具备审核依据的任务被误判为符合。

**Blocked by:** 01 — 语义审核运行时与证据包基础.

**Status:** completed

**Implementation:** `normative_scope.py` freezes declared/supplemental scope and exposes coverage blockers for the run context.

- [ ] 规范审核范围仅由“声明规范 + 审核员登记的作业类型必备规范”构成，并随运行冻结。
- [ ] 预检能展示版本、有效性、发布状态、同年版本冲突和覆盖缺口。
- [ ] 未覆盖、不可用或未确认适用的规范不得支持“符合”或“不符合”结论。
- [ ] 审核员可从控制台理解被阻塞任务及其原因。
