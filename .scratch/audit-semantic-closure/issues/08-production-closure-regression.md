# 08 — 生产闭环回归与交付验收

**What to build:** 部署方可以在项目标准 `env_agent` 环境中验证一条完整、可重复的生产审核路径：从已解析方案和审核上下文确认，到语义审核、人工复核和版本化正式报告，并得到明确的验收证据。

**Blocked by:** 02 — 规范范围确认与覆盖预检; 03 — 规范向量合规审核闭环; 04 — 受限图检索与图线索回溯; 05 — 图增强合理性审核闭环; 06 — 人工复核与首次正式报告发布; 07 — 报告更正与不可变版本.

**Status:** completed

**Implementation:** `test_production_closure.py`, `acceptance.py`, and the acceptance document provide the reproducible `env_agent` regression path.

- [ ] 在 `env_agent` 中运行现有审核/JSA 回归和新增生产闭环测试。
- [ ] 固定方案样本验证语义任务覆盖、证据追溯、局部失败隔离和图服务降级。
- [ ] 验证人工必办项门禁、首次发布、人工更正及报告版本关系。
- [ ] 验证同次 JSON/DOCX 一致性和 DOCX 渲染可读性。
- [ ] 产出可复现的验收命令与结果摘要，不包含 Gold 集、缺陷注入或方法对比实验。
