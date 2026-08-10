# 04 — 人工复核与首次正式报告发布 UI

**What to build:** 审核员可以在需要处置的审核结果旁完成确认、驳回、修改或补充，看到未处理必办项和发布门禁；门禁满足后在系统内发布正式报告并下载 JSON 与 DOCX。

**Blocked by:** 03 — 全量审核结果与分类型证据阅读.

**Status:** completed

**Implementation:** Added visible human action controls, unresolved-item gate, formal report publication, and JSON/DOCX download controls.

- [ ] 每个需处置结果提供有可见文字标签的人工复核操作、审核员标识和说明输入。
- [ ] 操作提交后，处置状态、剩余必办项数和追加操作历史在页面可见。
- [ ] 未处理必办项阻止发布并说明原因；满足条件后启用发布操作。
- [ ] 发布后显示发布者和快照摘要，并提供同一冻结快照生成的 JSON/DOCX 下载。
- [ ] `AppTest` 验证复核、发布门禁、发布成功和下载控件可用性。
