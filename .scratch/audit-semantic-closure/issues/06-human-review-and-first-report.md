# 06 — 人工复核与首次正式报告发布

**What to build:** 审核员可在智能审核初稿中逐项确认、驳回、修改或补充必办项；所有必办项明确处置后，可在系统内发布一份可对外提交的正式 DOCX 和内容一致的 JSON 报告。

**Blocked by:** 03 — 规范向量合规审核闭环; 05 — 图增强合理性审核闭环.

**Status:** backend-complete-ui-pending

**Implementation:** report freeze/export and append-only MySQL review/publish operations are implemented. Streamlit review and publish controls remain pending.

- [ ] 人工操作以追加审计记录保存，保留操作者标识、时间、处置动作和说明，不覆盖机器原始结果。
- [ ] 未处理的人工必办项会阻止正式报告发布，并向审核员说明阻塞范围。
- [ ] 系统内发布记录发布者与发布时间，不对接外部电子签名或审批平台。
- [ ] JSON 与 DOCX 源自同一冻结报告快照，包含任务覆盖、问题、人工处置、系统失败及证据附录。
- [ ] DOCX 渲染后可读，且与 JSON 的任务、问题和结论一致。
