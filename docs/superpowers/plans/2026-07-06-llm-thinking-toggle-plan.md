# LLM 思考模式开关 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为知识图谱构建的全部 LLM 请求增加默认关闭、界面显式开启的 Provider 感知思考模式开关。

**Architecture:** 在 `LLMConfig` 中保存统一布尔配置，由新的 `llm_thinking.py` 负责 Provider 参数映射和仅思考模型校验。流水线把配置传入实体抽取、实体对齐和三元组生成组件，四个调用点只展开统一适配器生成的参数；Streamlit 使用纯函数构造配置，便于不启动服务器即可测试。

**Tech Stack:** Python 3、OpenAI Python SDK、Streamlit、`unittest`、`unittest.mock`

---

## 文件结构

- Create: `kg_extract_build/llm_thinking.py`：唯一负责 Provider 思考参数映射与仅思考模型识别。
- Create: `kg_extract_build/tests/test_llm_thinking.py`：覆盖全部 Provider 的开关映射和仅思考模型规则。
- Modify: `kg_extract_build/run_config.py`：保存、校验、快照化并从环境变量读取开关。
- Modify: `kg_extract_build/tests/test_run_config.py`：覆盖默认值、环境变量、快照和启动前拒绝规则。
- Modify: `kg_extract_build/extractor.py`：实体抽取请求携带统一思考参数。
- Modify: `kg_extract_build/entity_aligner.py`：实体对齐请求携带统一思考参数。
- Modify: `kg_extract_build/triplets.py`：单实体和批量关系请求携带统一思考参数。
- Modify: `kg_extract_build/pipeline.py`：把 Provider 与开关传递给三个组件。
- Create: `kg_extract_build/tests/test_llm_call_options.py`：直接验证四个真实请求调用点。
- Modify: `kg_extract_build/dashboard_run.py`：增加复选框、提示和纯配置构造函数。
- Modify: `kg_extract_build/tests/test_dashboard_run.py`：验证界面辅助函数默认关闭并正确传值。
- Modify: `kg_extract_build/.env.example`：记录命令行启动时的开关。
- Modify: `kg_extract_build/README.md`：说明默认行为、界面操作和仅思考模型限制。

### Task 1: Provider 思考参数适配器

**Files:**
- Create: `kg_extract_build/llm_thinking.py`
- Create: `kg_extract_build/tests/test_llm_thinking.py`

- [ ] **Step 1: 编写参数映射失败测试**

创建测试，要求七类 Provider 在关闭和开启时返回精确参数：

```python
import unittest

from kg_extract_build.llm_thinking import build_thinking_options


class LLMThinkingOptionsTests(unittest.TestCase):
    def test_provider_options_explicitly_disable_thinking(self):
        expected = {
            "zhipu": {
                "extra_body": {"thinking": {"type": "disabled"}}
            },
            "deepseek": {
                "extra_body": {"thinking": {"type": "disabled"}}
            },
            "qwen": {"extra_body": {"enable_thinking": False}},
            "modelscope": {
                "extra_body": {"enable_thinking": False}
            },
            "ollama": {"reasoning_effort": "none"},
            "huggingface": {"reasoning_effort": "none"},
            "custom": {"reasoning_effort": "none"},
        }
        for provider_id, options in expected.items():
            with self.subTest(provider_id=provider_id):
                self.assertEqual(
                    build_thinking_options(provider_id, False),
                    options,
                )

    def test_provider_options_enable_thinking_only_when_requested(self):
        expected = {
            "zhipu": {
                "extra_body": {"thinking": {"type": "enabled"}}
            },
            "deepseek": {
                "extra_body": {"thinking": {"type": "enabled"}}
            },
            "qwen": {"extra_body": {"enable_thinking": True}},
            "modelscope": {
                "extra_body": {"enable_thinking": True}
            },
            "ollama": {"reasoning_effort": "high"},
            "huggingface": {"reasoning_effort": "high"},
            "custom": {"reasoning_effort": "high"},
        }
        for provider_id, options in expected.items():
            with self.subTest(provider_id=provider_id):
                self.assertEqual(
                    build_thinking_options(provider_id, True),
                    options,
                )

    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知"):
            build_thinking_options("missing", False)
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_llm_thinking -v
```

Expected: FAIL，原因是 `kg_extract_build.llm_thinking` 尚不存在。

- [ ] **Step 3: 实现最小 Provider 映射**

创建：

```python
"""Provider-specific controls for LLM thinking mode."""

_THINKING_STYLE = {
    "zhipu": "thinking_type",
    "deepseek": "thinking_type",
    "qwen": "enable_thinking",
    "modelscope": "enable_thinking",
    "ollama": "reasoning_effort",
    "huggingface": "reasoning_effort",
    "custom": "reasoning_effort",
}


def build_thinking_options(provider_id: str, enabled: bool) -> dict:
    try:
        style = _THINKING_STYLE[provider_id]
    except KeyError as exc:
        raise ValueError(f"未知的 LLM 提供商：{provider_id}") from exc
    enabled = bool(enabled)
    if style == "thinking_type":
        mode = "enabled" if enabled else "disabled"
        return {"extra_body": {"thinking": {"type": mode}}}
    if style == "enable_thinking":
        return {"extra_body": {"enable_thinking": enabled}}
    return {"reasoning_effort": "high" if enabled else "none"}
```

- [ ] **Step 4: 运行适配器测试并确认通过**

Run: Task 1 Step 2 的命令。

Expected: 3 tests PASS。

- [ ] **Step 5: 编写仅思考模型失败测试**

在同一测试文件增加：

```python
from kg_extract_build.llm_thinking import is_thinking_only_model


class ThinkingOnlyModelTests(unittest.TestCase):
    def test_known_thinking_only_models_are_detected(self):
        cases = (
            ("deepseek", "deepseek-reasoner"),
            ("huggingface", "deepseek-ai/DeepSeek-R1"),
            ("qwen", "QwQ-32B"),
            ("modelscope", "Qwen3-32B-Thinking"),
            ("ollama", "gpt-oss:20b"),
        )
        for provider_id, model in cases:
            with self.subTest(model=model):
                self.assertTrue(
                    is_thinking_only_model(provider_id, model)
                )

    def test_hybrid_or_non_thinking_models_are_not_rejected(self):
        cases = (
            ("deepseek", "deepseek-chat"),
            ("zhipu", "glm-4.5-air"),
            ("qwen", "qwen-plus"),
            ("ollama", "qwen3:8b"),
        )
        for provider_id, model in cases:
            with self.subTest(model=model):
                self.assertFalse(
                    is_thinking_only_model(provider_id, model)
                )
```

- [ ] **Step 6: 运行测试并确认因函数缺失失败**

Run: Task 1 Step 2 的命令。

Expected: FAIL，原因是 `is_thinking_only_model` 尚不存在。

- [ ] **Step 7: 实现保守的仅思考模型识别**

在 `llm_thinking.py` 增加：

```python
def is_thinking_only_model(provider_id: str, model: str) -> bool:
    normalized = str(model).strip().lower()
    common_markers = (
        "reasoner",
        "deepseek-r1",
        "qwq",
        "thinking",
    )
    if any(marker in normalized for marker in common_markers):
        return True
    return provider_id == "ollama" and "gpt-oss" in normalized
```

- [ ] **Step 8: 运行测试并提交**

Run: Task 1 Step 2 的命令。

Expected: 全部 PASS。

```powershell
git add kg_extract_build/llm_thinking.py kg_extract_build/tests/test_llm_thinking.py
git commit -m "功能：新增LLM思考参数适配器"
```

### Task 2: 配置默认值、环境变量、快照与校验

**Files:**
- Modify: `kg_extract_build/run_config.py:123-137`
- Modify: `kg_extract_build/run_config.py:161-209`
- Modify: `kg_extract_build/run_config.py:242-278`
- Modify: `kg_extract_build/tests/test_run_config.py`

- [ ] **Step 1: 编写默认关闭和快照失败测试**

在 `test_run_config.py` 增加：

```python
def test_llm_thinking_is_disabled_by_default_and_snapshotted(self):
    llm = run_config.LLMConfig(
        provider_id="deepseek",
        api_key="secret",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    )
    self.assertFalse(llm.enable_thinking)
    self.assertFalse(llm.sanitized()["enable_thinking"])
```

- [ ] **Step 2: 运行测试并确认字段缺失失败**

Run:

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_run_config -v
```

Expected: FAIL，`LLMConfig` 没有 `enable_thinking`。

- [ ] **Step 3: 增加配置字段和快照字段**

将字段追加在有默认值的位置，避免破坏现有位置参数调用：

```python
@dataclass(frozen=True)
class LLMConfig:
    provider_id: str
    api_key: str = field(repr=False)
    base_url: str
    model: str
    enable_thinking: bool = False
```

在 `sanitized()` 返回值中增加：

```python
"enable_thinking": self.enable_thinking,
```

- [ ] **Step 4: 运行配置测试并确认通过**

Run: Task 2 Step 2 的命令。

Expected: 新增测试 PASS，原测试不回归。

- [ ] **Step 5: 编写环境变量和仅思考模型失败测试**

增加：

```python
def test_from_settings_reads_explicit_thinking_true(self):
    with mock.patch.dict(
        os.environ,
        {
            "LLM_PROVIDER": "ollama",
            "LLM_ENABLE_THINKING": "YES",
        },
        clear=False,
    ):
        config = run_config.PipelineConfig.from_settings()
    self.assertTrue(config.llm.enable_thinking)

def test_from_settings_defaults_thinking_to_false(self):
    with mock.patch.dict(os.environ, {}, clear=False):
        with mock.patch.dict(
            os.environ, {"LLM_ENABLE_THINKING": ""}, clear=False
        ):
            config = run_config.PipelineConfig.from_settings()
    self.assertFalse(config.llm.enable_thinking)

def test_thinking_only_model_requires_explicit_enable(self):
    with tempfile.TemporaryDirectory() as folder:
        Path(folder, "document.md").write_text(
            "content", encoding="utf-8"
        )
        config = self.make_config(folder)
        config = replace(
            config,
            llm=replace(
                config.llm,
                model="deepseek-reasoner",
                enable_thinking=False,
            ),
        )
        with self.assertRaisesRegex(ValueError, "仅思考模型"):
            config.validate()
        replace(
            config,
            llm=replace(config.llm, enable_thinking=True),
        ).validate()
```

- [ ] **Step 6: 运行测试并确认校验尚未实现而失败**

Run: Task 2 Step 2 的命令。

Expected: 至少仅思考模型测试 FAIL。

- [ ] **Step 7: 实现环境变量解析与配置校验**

在 `run_config.py` 增加：

```python
from .llm_thinking import is_thinking_only_model


def _env_flag(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
```

在 `PipelineConfig.validate()` 的模型非空校验之后增加：

```python
if (
    not self.llm.enable_thinking
    and is_thinking_only_model(
        self.llm.provider_id,
        self.llm.model,
    )
):
    raise ValueError(
        "当前模型属于仅思考模型，无法保证关闭思考；"
        "请更换模型或勾选“启用思考模式”"
    )
```

在 `from_settings()` 构造 `LLMConfig` 时增加：

```python
enable_thinking=_env_flag(
    os.environ.get("LLM_ENABLE_THINKING", "")
),
```

- [ ] **Step 8: 运行配置测试并提交**

Run: Task 2 Step 2 的命令。

Expected: 全部 PASS。

```powershell
git add kg_extract_build/run_config.py kg_extract_build/tests/test_run_config.py
git commit -m "功能：配置并校验LLM思考模式"
```

### Task 3: 四个真实 LLM 调用点

**Files:**
- Modify: `kg_extract_build/extractor.py:15-27,177-185`
- Modify: `kg_extract_build/entity_aligner.py:52-67,257-265`
- Modify: `kg_extract_build/triplets.py:12-25,32-42,109-114`
- Modify: `kg_extract_build/pipeline.py:217-232,434-442`
- Create: `kg_extract_build/tests/test_llm_call_options.py`
- Modify: `kg_extract_build/tests/test_triplet_batching.py`

- [ ] **Step 1: 编写组件请求参数失败测试**

新测试文件使用一个记录 `create(**kwargs)` 的假客户端，分别构造三个组件并调用：

```python
class RecordingCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = type("Message", (), {"content": self.content})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()
```

实体抽取断言：

```python
self.assertEqual(
    completions.calls[0]["extra_body"],
    {"thinking": {"type": "disabled"}},
)
```

实体对齐断言使用同一关闭参数。单实体关系抽取和现有批量关系测试分别断言：

```python
self.assertEqual(
    completions.calls[0]["extra_body"],
    {"enable_thinking": False},
)
```

测试构造函数必须传入 `provider_id` 和 `enable_thinking=False`，证明参数来自公开构造接口，而不是测试直接写入内部属性。

- [ ] **Step 2: 运行测试并确认构造函数不接受新参数**

Run:

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_llm_call_options kg_extract_build.tests.test_triplet_batching -v
```

Expected: FAIL，组件构造函数尚未接受 `provider_id` / `enable_thinking`，或请求缺少 `extra_body`。

- [ ] **Step 3: 三个组件统一保存适配参数**

三个组件均导入：

```python
from .llm_thinking import build_thinking_options
```

三个构造函数均追加：

```python
provider_id="custom",
enable_thinking=False,
```

并保存：

```python
self._thinking_options = build_thinking_options(
    provider_id,
    enable_thinking,
)
```

四个 `chat.completions.create()` 调用均增加：

```python
**self._thinking_options,
```

- [ ] **Step 4: 运行调用点测试并确认通过**

Run: Task 3 Step 2 的命令。

Expected: 新增调用点测试和批量关系测试全部 PASS。

- [ ] **Step 5: 编写流水线参数传递失败测试**

在 `test_pipeline_control.py` 增加一个最小流水线测试，patch 三个组件并断言：

```python
extractor_cls.assert_called_once()
self.assertEqual(extractor_cls.call_args.kwargs["provider_id"], "qwen")
self.assertTrue(
    extractor_cls.call_args.kwargs["enable_thinking"]
)
self.assertEqual(aligner_cls.call_args.kwargs["provider_id"], "qwen")
```

对 `TripletGenerator` 使用已有能进入关系抽取阶段的 fixture，断言相同两个关键字参数。

- [ ] **Step 6: 运行流水线测试并确认参数尚未传递而失败**

Run:

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_pipeline_control -v
```

Expected: FAIL，mock 的调用参数中没有 `provider_id` 或 `enable_thinking`。

- [ ] **Step 7: 流水线传递配置**

三个组件的构造调用都增加：

```python
provider_id=config.llm.provider_id,
enable_thinking=config.llm.enable_thinking,
```

- [ ] **Step 8: 运行相关测试并提交**

Run:

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_llm_call_options kg_extract_build.tests.test_triplet_batching kg_extract_build.tests.test_pipeline_control kg_extract_build.tests.test_pipeline_relation_batching -v
```

Expected: 全部 PASS。

```powershell
git add kg_extract_build/extractor.py kg_extract_build/entity_aligner.py kg_extract_build/triplets.py kg_extract_build/pipeline.py kg_extract_build/tests/test_llm_call_options.py kg_extract_build/tests/test_triplet_batching.py kg_extract_build/tests/test_pipeline_control.py
git commit -m "功能：全部知识图谱请求支持思考开关"
```

### Task 4: Streamlit 开关与运行配置

**Files:**
- Modify: `kg_extract_build/dashboard_run.py:21-57,210-245,337-371`
- Modify: `kg_extract_build/tests/test_dashboard_run.py`

- [ ] **Step 1: 编写纯辅助函数失败测试**

在 `test_dashboard_run.py` 导入并测试：

```python
from kg_extract_build.dashboard_run import (
    build_llm_config,
    thinking_mode_notice,
)


def test_thinking_notice_explains_default_cost_behavior(self):
    message = thinking_mode_notice(False)
    self.assertIn("默认关闭", message)
    self.assertIn("Token", message)

def test_dashboard_llm_config_forwards_thinking_choice(self):
    config = build_llm_config(
        provider_id="qwen",
        api_key="secret",
        base_url="https://example.test/v1",
        model="qwen-plus",
        enable_thinking=True,
    )
    self.assertTrue(config.enable_thinking)
```

- [ ] **Step 2: 运行测试并确认辅助函数缺失失败**

Run:

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_dashboard_run -v
```

Expected: FAIL，两个辅助函数尚不存在。

- [ ] **Step 3: 实现纯辅助函数**

在 `dashboard_run.py` 的纯函数区增加：

```python
def thinking_mode_notice(enabled):
    if enabled:
        return (
            "已启用思考模式：可能提升复杂任务效果，"
            "但会增加响应时间和推理 Token 消耗。"
        )
    return "默认关闭思考模式，以减少响应时间和推理 Token 消耗。"


def build_llm_config(
    provider_id,
    api_key,
    base_url,
    model,
    enable_thinking=False,
):
    return LLMConfig(
        provider_id=provider_id,
        api_key=api_key,
        base_url=base_url,
        model=model,
        enable_thinking=bool(enable_thinking),
    )
```

- [ ] **Step 4: 运行辅助函数测试并确认通过**

Run: Task 4 Step 2 的命令。

Expected: 全部 PASS。

- [ ] **Step 5: 在界面增加默认未勾选复选框**

在模型名称下方增加：

```python
enable_thinking = st.checkbox(
    "启用思考模式",
    value=False,
    disabled=registry.is_running,
)
st.caption(thinking_mode_notice(enable_thinking))
```

把直接构造 `LLMConfig(...)` 攓为：

```python
llm=build_llm_config(
    provider_id=provider_id,
    api_key=api_key,
    base_url=base_url.strip(),
    model=model.strip(),
    enable_thinking=enable_thinking,
),
```

- [ ] **Step 6: 运行界面辅助测试和配置测试**

Run:

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_dashboard_run kg_extract_build.tests.test_run_config -v
```

Expected: 全部 PASS。

- [ ] **Step 7: 提交界面改动**

```powershell
git add kg_extract_build/dashboard_run.py kg_extract_build/tests/test_dashboard_run.py
git commit -m "功能：界面增加LLM思考模式开关"
```

### Task 5: 环境示例、中文文档与完整回归

**Files:**
- Modify: `kg_extract_build/.env.example:42-48`
- Modify: `kg_extract_build/README.md:50-130`
- Modify: `kg_extract_build/tests/test_provider_docs.py`

- [ ] **Step 1: 编写文档契约失败测试**

在 `test_provider_docs.py` 增加：

```python
def test_env_example_documents_thinking_default(self):
    text = Path("kg_extract_build/.env.example").read_text(
        encoding="utf-8"
    )
    self.assertIn("LLM_ENABLE_THINKING=0", text)

def test_readme_explains_ui_thinking_switch(self):
    text = Path("kg_extract_build/README.md").read_text(
        encoding="utf-8"
    )
    self.assertIn("启用思考模式", text)
    self.assertIn("默认关闭", text)
```

- [ ] **Step 2: 运行测试并确认文档内容缺失失败**

Run:

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_provider_docs -v
```

Expected: FAIL，环境示例和 README 尚未包含开关说明。

- [ ] **Step 3: 更新环境示例与 README**

在 `.env.example` 的 LLM 配置中增加：

```dotenv
# 默认关闭；仅在明确需要推理模式时设为 1
LLM_ENABLE_THINKING=0
```

README 说明：

- Streamlit 首次打开时复选框不勾选。
- 勾选后才向所有知识图谱 LLM 阶段发送开启参数。
- 开启会增加延迟与推理 Token。
- 已知仅思考模型未勾选时会在启动前报错。
- 命令行可通过 `LLM_ENABLE_THINKING=1` 开启。

- [ ] **Step 4: 运行文档测试并确认通过**

Run: Task 5 Step 2 的命令。

Expected: 全部 PASS。

- [ ] **Step 5: 运行完整单元测试**

Run:

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest discover -s kg_extract_build/tests -v
```

Expected: 所有测试 PASS，0 failures，0 errors。

- [ ] **Step 6: 运行语法编译检查**

Run:

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m compileall -q kg_extract_build
```

Expected: exit code 0，无语法错误。

- [ ] **Step 7: 检查差异和敏感信息**

Run:

```powershell
git diff --check
git status --short
git diff -- kg_extract_build
```

Expected: 无空白错误；差异仅包含计划内文件；没有 API Key。

- [ ] **Step 8: 提交文档并做提交后验证**

```powershell
git add kg_extract_build/.env.example kg_extract_build/README.md kg_extract_build/tests/test_provider_docs.py
git commit -m "文档：说明LLM思考模式默认关闭"
```

再次运行 Task 5 Step 5 和 Step 6，并确认 `git status --short --branch` 仅保留用户原有的 `.claude/` 未跟踪目录。
