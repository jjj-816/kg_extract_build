# 07 — 报告更正与不可变版本

**What to build:** 审核员在正式报告发布后需要更正人工说明或处置结论时，系统创建新的可追溯报告版本，而不覆盖原报告；只有审核输入或冻结证据变化才要求重新机器审核。

**Blocked by:** 06 — 人工复核与首次正式报告发布.

**Status:** backend-complete-ui-pending

**Implementation:** immutable correction versions and re-audit gating are implemented. Streamlit version browsing and correction controls remain pending.

- [ ] 每个报告版本保留自身报告快照、导出文件、创建者、时间、变更原因及前序版本关联。
- [ ] 人工更正可生成新版本而不重跑机器审核，且原版本和原证据保持可读。
- [ ] 源方案、审核上下文或证据快照变化时，系统拒绝仅创建更正版本并要求新建审核运行。
- [ ] 界面可区分初稿、已发布版本和后续更正版本。
- [ ] 集成测试验证版本不可变、版本关联及重新审核门禁。
