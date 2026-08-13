# Final review fixes report

## Scope

仅修复最终整体复审指出的 3 个 Important：执行结果证据持久化、规范版本历史引用保护、声明规范自动合规证据边界。

## Fix 1: execution evidence persistence

- 根因：`save_execution_results` 将所有证据硬编码为 `document`，并对每条证据强取 `block_id`；规范条款与图线索没有该字段，成功语义运行因此抛出 `KeyError` 并回滚。
- 修复：依据 `evidence_type` 写入 `audit_task_evidence.evidence_role`；文档证据写 `document_block_id`，规范条款与图线索分别用 `clause_id`、`clue_id` 写 `external_evidence_id`，完整快照仍写 `evidence_snapshot`。
- TDD：新增事务边界测试，RED 为规范证据触发 `KeyError: block_id`，GREEN 验证三类证据的列映射以及成功路径 `commit=1`、`rollback=0`。

## Fix 2: historical normative version references

- 根因：原查询假设 `audit_retrieval_candidate` 存在 `version_id`、`clause_id`，但 `audit/schema.sql` 中该表没有这两个字段，真实 MySQL schema 无法执行。
- 修复：只使用真实字段：直接查询 `audit_declared_norm.version_id`、`audit_applicability_result.version_id`，并从 `audit_task_evidence.evidence_snapshot` 的 `$.version_id` 检查已冻结的规范证据引用；通过 `audit_task_execution.execution_id/run_id` 返回历史运行引用。
- TDD：新增 schema 契约测试，RED 捕获旧 SQL 中不存在的字段，GREEN 验证三条真实引用通道都被检查。

## Fix 3: declared-only compliance evidence

- 根因：候选匹配把 `scope.family_ids` 当作白名单；该字段是 declared 与 supplemental 的合并，导致 supplemental 规范直接进入自动合规证据。
- 修复：自动证据匹配只读取并规范化 `scope.declared_families`，不再读取 `scope.family_ids`；未声明的 supplemental 候选被标记为 `not_declared_norm`，仅产生 `declared_norm_omission` 提示。
- TDD：新增 declared 与 supplemental 同时存在的回归测试，RED 显示二者都被选入，GREEN 验证仅 canonicalized declared 标准号匹配成功。

## Verification

- 目标与相邻测试：`23 passed`。
- `test_compliance_runtime.py`：`7 passed`（系统 Python 的 pandas/numpy 存在 ABI 冲突，使用只替代未被该测试触及的 pandas 导入壳运行；未修改依赖环境）。
- `git diff --check`：通过。

## Remaining concern

当前机器全量 pytest 仍会在导入 pandas 时因环境中的 pandas/numpy ABI 不兼容而中断收集；这是既有环境问题，不在本次三项修复范围内。

## Final rereview follow-up: opaque normative identity

- 残留根因：候选没有规范代码、名称或可识别版本号时，声明匹配函数仍默认返回真；生产 `NormativeSearcher` 也没有把已从 MySQL index row 读到的规范身份投影到 evidence。
- 修复：无足够规范身份的候选一律不能进入自动证据，只按 `not_declared_norm` 产生 `declared_norm_omission`；生产 evidence 现在携带权威的 `family_id`、`standard_code`、`standard_code_base`、`canonical_name`、`display_name`。
- TDD：新增 opaque supplemental 拒绝测试、实际生产形态声明标准号选中测试、实际生产形态未声明规范遗漏测试，并扩展 `NormativeSearcher` 测试校验身份投影。RED 为 opaque 候选错误选中及生产 evidence 缺少 `standard_code`；GREEN 后相关链路 `18 passed`。
