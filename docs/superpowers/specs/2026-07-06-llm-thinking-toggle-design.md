# 知识图谱构建 LLM 思考模式开关设计

## 背景与目标

知识图谱构建流水线目前在实体抽取、实体对齐、逐实体关系抽取和批量关系抽取阶段直接调用 OpenAI 兼容接口，没有显式控制模型的思考模式。部分新模型默认开启思考，导致响应延迟和推理 Token 消耗增加。

本次改动的目标是：

- 所有知识图谱构建阶段的 LLM 请求默认显式关闭思考模式。
- Streamlit 运行界面提供“启用思考模式”选项，只有用户主动勾选后才开启。
- 不同 Provider 使用各自支持的参数，不向所有接口盲目发送同一个字段。
- 未勾选时若识别到仅支持思考的模型，在流水线启动前明确报错。
- 实验快照记录思考模式设置，便于论文实验复现。

## 非目标

- 不展示或保存模型的思维链内容。
- 不增加思考强度、思考预算等二级配置。
- 不自动更换用户选择的模型。
- 不在请求失败后静默删除思考参数并重试，因为这会破坏“默认关闭”的语义。

## 方案选择

采用“统一配置 + Provider 参数适配器”方案。

不在四个调用点分别编写 Provider 判断，也不依赖提示词要求模型停止思考。所有调用点只接收统一的 `enable_thinking` 布尔值，并通过同一个适配器生成请求参数。

这样可以避免调用行为漂移，并能独立测试各 Provider 的映射。

## 配置与界面

`LLMConfig` 新增字段：

```python
enable_thinking: bool = False
```

默认值必须为 `False`，保证命令行旧调用、测试构造和 Streamlit 界面都默认关闭思考。

Streamlit 的 LLM 配置区域新增复选框：

- 标签：`启用思考模式`
- 默认值：不勾选
- 提示：`默认关闭。开启后可能提高复杂任务效果，但会增加响应时间和推理 Token 消耗。`
- 流水线运行期间禁用，行为与其他运行参数一致。

`PipelineConfig.sanitized_snapshot()` 中的 `llm` 快照增加 `enable_thinking`，该字段不涉及秘密信息。

通过 `PipelineConfig.from_settings()` 启动时，支持环境变量 `LLM_ENABLE_THINKING`，仅将 `1`、`true`、`yes`、`on`（忽略大小写）解释为开启，其余值均为关闭；未配置时默认关闭。

## Provider 参数适配

新增独立模块集中提供两个职责：

1. 根据 Provider 和开关值生成 `chat.completions.create()` 的附加参数。
2. 在启动前校验“关闭思考”与模型能力是否冲突。

参数映射如下：

| Provider | 关闭 | 开启 |
| --- | --- | --- |
| 智谱 | `extra_body={"thinking": {"type": "disabled"}}` | `extra_body={"thinking": {"type": "enabled"}}` |
| DeepSeek | `extra_body={"thinking": {"type": "disabled"}}` | `extra_body={"thinking": {"type": "enabled"}}` |
| Qwen / 阿里云百炼 | `extra_body={"enable_thinking": false}` | `extra_body={"enable_thinking": true}` |
| ModelScope | `extra_body={"enable_thinking": false}` | `extra_body={"enable_thinking": true}` |
| Ollama | `extra_body={"think": false}` | `extra_body={"think": true}` |
| Hugging Face | `reasoning_effort="none"` | `reasoning_effort="high"` |
| 自定义 OpenAI 兼容接口 | `reasoning_effort="none"` | `reasoning_effort="high"` |

自定义接口的能力无法在本地预先推断。如果接口不接受标准 `reasoning_effort` 参数，保留原始 API 错误并让该 LLM 调用失败，不进行可能重新开启默认思考的降级重试。

上述映射依据各平台当前官方文档：

- DeepSeek：<https://api-docs.deepseek.com/zh-cn/guides/thinking_mode>
- 智谱：<https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode>
- 阿里云百炼：<https://help.aliyun.com/zh/model-studio/deep-thinking>
- Ollama：<https://docs.ollama.com/capabilities/thinking>
- Hugging Face：<https://huggingface.co/docs/inference-providers/tasks/chat-completion>

## 仅思考模型校验

当 `enable_thinking=False` 时，对规范化后的模型名称执行保守校验。已知仅思考模型标识包括：

- `reasoner`
- `thinking`
- `deepseek-r1`
- `qwq`
- Ollama 下的 `gpt-oss`

命中后，`PipelineConfig.validate()` 抛出中文 `ValueError`，提示该模型无法保证关闭思考，应更换支持混合思考或非思考模式的模型，或者主动勾选“启用思考模式”。

该校验只覆盖能够从模型名称可靠识别的常见模型。对于自定义别名和远程平台动态路由，最终仍以 Provider 是否接受关闭参数为准；程序不会静默移除关闭参数。

## 调用链改造

流水线创建以下三个组件时，将 `provider_id` 和 `enable_thinking` 一并传入：

- `LongDocLLMEntityExtractor`
- `EntityAligner`
- `TripletGenerator`

三个组件在构造时生成并保存只读的思考参数；四个真实调用点均以展开参数的方式传给 `chat.completions.create()`：

- 实体切片抽取
- 实体候选组对齐
- 单实体三元组生成
- 共享上下文批量三元组生成

基础请求中的 `model`、`messages`、`temperature` 等现有参数保持不变。思考模式返回的 `reasoning_content` 不写入实验记录，流水线仍只解析最终 `content`。

## 错误处理

- 配置阶段识别到仅思考模型：阻止启动并在界面显示中文错误。
- Provider 不支持对应参数：沿用现有调用失败记录和脱敏机制，不降级重试。
- 某阶段全部 LLM 调用失败：继续沿用现有“全失败则实验失败”逻辑。
- API Key、Base URL 等秘密信息仍按现有规则脱敏。

## 测试策略

按测试驱动方式实现，至少覆盖：

1. `LLMConfig` 默认关闭思考，快照正确记录布尔值。
2. 环境变量缺省时关闭，真值字符串时开启。
3. 七类 Provider 的关闭和开启参数映射正确。
4. 未关闭参数不会被静默省略。
5. 未勾选时，常见仅思考模型在配置校验阶段被拒绝。
6. 勾选后，同一模型允许进入流水线。
7. Streamlit 创建的运行配置正确接收复选框值。
8. 实体抽取、实体对齐、单实体关系抽取和批量关系抽取四个调用点均携带适配后的参数。
9. 现有流水线控制、批量关系抽取和配置测试无回归。

## 验收标准

- 首次打开界面时，“启用思考模式”未勾选。
- 使用支持混合思考的模型运行时，每个 LLM 请求都显式携带关闭参数。
- 勾选后，每个 LLM 请求都显式携带开启参数。
- 已知仅思考模型在未勾选时不能启动。
- 实验快照可区分开启与关闭两类实验。
- 全部自动化测试通过，且提交使用中文说明。
