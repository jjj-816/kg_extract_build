# 03 — 全量审核结果与分类型证据阅读

**What to build:** 审核员可在现有结果阅读区筛选模板完整性问题、规范合规结论、工程合理性风险、人工核验、线下完善、JSA 提示和系统审核失败，并在详情中按证据类型完成追溯。

**Blocked by:** 02 — 语义审核执行反馈与任务状态.

**Status:** completed

**Implementation:** Result details now separate document evidence, normative clauses, and graph clues with distinct labels and traceability fields.

- [ ] 结果筛选保留现有交互模式，并增加语义合规与工程合理性结果类型。
- [ ] 文档证据展示稳定位置和原文；规范证据展示完整条款、版本和适用性；图线索展示历史案例身份、关系断言和证据句。
- [ ] 图线索的文字与视觉标签不被呈现为规范不符合依据。
- [ ] 覆盖缺口、系统审核失败和降级信息与方案问题清晰区分。
- [ ] `AppTest` 验证筛选、详情展开与三类证据的可见性和语义区分。
