# Streamlit 实体提取流水线控制台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 将实体提取流水线、参数配置、安全停止和实时进度监控完整接入现有 Streamlit 应用，使用户只启动一个 Streamlit 服务即可完成实验。

**架构：** 使用不可变 `PipelineConfig` 显式传递一次实验的参数；使用 `PipelineEvent`、线程安全队列和 `CancellationToken` 连接后台流水线与前端；使用进程内 `PipelineRunRegistry` 保持 Streamlit rerun 期间的任务状态。现有 MySQL、Milvus 和历史看板保持不变。

**技术栈：** Python 3.11、Streamlit、OpenAI Python SDK、MySQL/PyMySQL、Milvus/PyMilvus、SentenceTransformer、`unittest`

**项目管理：** 全部工作在 `feature` 分支完成；每次提交前确认分支；Git commit 信息统一使用中文。

---

## 文件结构

- 新建 `kg_extract_build/run_config.py`：LLM 提供商预设、运行配置、校验、密钥解析和脱敏快照。
- 修改 `kg_extract_build/documents.py`：只读扫描本机目录、返回文件元数据、按用户选择加载文件。
- 修改 `kg_extract_build/extractor.py`：接收可配置切片长度和取消令牌。
- 修改 `kg_extract_build/entity_aligner.py`：在候选组之间检查取消令牌。
- 新建 `kg_extract_build/runtime.py`：事件、取消令牌、事件归并和单任务运行注册表。
- 修改 `kg_extract_build/pipeline.py`：显式接收配置、事件回调和取消令牌。
- 新建 `kg_extract_build/dashboard_run.py`：运行实验页面及可独立测试的界面辅助函数。
- 修改 `kg_extract_build/dashboard.py`：增加默认“运行实验”导航并复用历史页面。
- 修改 `kg_extract_build/.env.example`、`kg_extract_build/README.md`、`README.md`：补充提供商和单命令启动说明。
- 新建对应测试文件，继续使用当前 `unittest` 风格。

### 任务 1：建立提供商注册表和安全运行配置

**文件：**

- 新建：`kg_extract_build/run_config.py`
- 新建：`kg_extract_build/tests/test_run_config.py`

- [ ] **步骤 1：先写提供商、校验和脱敏测试**

```python
# kg_extract_build/tests/test_run_config.py
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from kg_extract_build.run_config import (
    ChunkingConfig,
    LLMConfig,
    PipelineConfig,
    PROVIDERS,
    redact_text,
    resolve_provider_api_key,
)


class RunConfigTests(unittest.TestCase):
    def test_contains_all_approved_providers(self):
        self.assertEqual(
            set(PROVIDERS),
            {"zhipu", "deepseek", "ollama", "qwen", "modelscope", "huggingface", "custom"},
        )

    def test_override_key_has_priority_over_environment(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-secret"}, clear=False):
            self.assertEqual(resolve_provider_api_key("deepseek", "ui-secret"), "ui-secret")

    def test_provider_environment_falls_back_to_legacy_key(self):
        with patch.dict(os.environ, {"LLM_API_KEY": "legacy-secret"}, clear=True):
            self.assertEqual(resolve_provider_api_key("zhipu"), "legacy-secret")

    def test_ollama_uses_non_secret_placeholder(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_provider_api_key("ollama"), "ollama")

    def test_snapshot_never_contains_api_key(self):
        config = PipelineConfig(
            run_name="测试实验",
            document_folder=Path("docs"),
            selected_files=("a.md",),
            llm=LLMConfig(
                provider_id="deepseek",
                api_key="top-secret",
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
            ),
            chunking=ChunkingConfig(),
        )
        snapshot = config.sanitized_snapshot()
        self.assertNotIn("api_key", snapshot["llm"])
        self.assertNotIn("top-secret", repr(snapshot))

    def test_redacts_secret_and_authorization_header(self):
        message = redact_text(
            "request failed: Authorization: Bearer top-secret",
            secrets=("top-secret",),
        )
        self.assertNotIn("top-secret", message)
        self.assertIn("Bearer ***", message)

    def test_rejects_missing_online_provider_key(self):
        config = PipelineConfig(
            run_name="测试实验",
            document_folder=Path("."),
            selected_files=("a.md",),
            llm=LLMConfig("deepseek", "", "https://api.deepseek.com", "deepseek-chat"),
        )
        with self.assertRaisesRegex(ValueError, "API Key"):
            config.validate()

    def test_chunk_size_range_is_validated(self):
        config = PipelineConfig(
            run_name="测试实验",
            document_folder=Path("."),
            selected_files=("a.md",),
            llm=LLMConfig("ollama", "ollama", "http://localhost:11434/v1/", "qwen3"),
            chunking=ChunkingConfig(max_chars=199),
        )
        with self.assertRaisesRegex(ValueError, "200"):
            config.validate()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：运行测试并确认按预期失败**

运行：

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_run_config -v
```

预期：失败，错误为 `ModuleNotFoundError: No module named 'kg_extract_build.run_config'`。

- [ ] **步骤 3：实现最小配置模块**

```python
# kg_extract_build/run_config.py
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"), override=False)
except ImportError:
    pass


@dataclass(frozen=True)
class ProviderPreset:
    provider_id: str
    label: str
    default_base_url: str
    env_keys: tuple[str, ...]
    requires_api_key: bool = True


PROVIDERS = {
    "zhipu": ProviderPreset(
        "zhipu", "智谱", "https://open.bigmodel.cn/api/paas/v4/",
        ("ZAI_API_KEY", "LLM_API_KEY"),
    ),
    "deepseek": ProviderPreset(
        "deepseek", "DeepSeek", "https://api.deepseek.com",
        ("DEEPSEEK_API_KEY", "LLM_API_KEY"),
    ),
    "ollama": ProviderPreset(
        "ollama", "Ollama", "http://localhost:11434/v1/", (), False,
    ),
    "qwen": ProviderPreset(
        "qwen", "Qwen / 阿里云百炼",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ("DASHSCOPE_API_KEY",),
    ),
    "modelscope": ProviderPreset(
        "modelscope", "ModelScope / 魔搭", "", ("MODELSCOPE_API_TOKEN",),
    ),
    "huggingface": ProviderPreset(
        "huggingface", "Hugging Face",
        "https://router.huggingface.co/v1", ("HF_TOKEN",),
    ),
    "custom": ProviderPreset(
        "custom", "本地 / 自定义 OpenAI 兼容接口",
        os.getenv("LLM_BASE_URL", ""), ("LLM_API_KEY",),
    ),
}


def resolve_provider_api_key(
    provider_id: str,
    override: str = "",
    environ: Mapping[str, str] | None = None,
) -> str:
    if override.strip():
        return override.strip()
    preset = PROVIDERS[provider_id]
    source = os.environ if environ is None else environ
    for key in preset.env_keys:
        value = source.get(key, "").strip()
        if value:
            return value
    return "ollama" if not preset.requires_api_key else ""


def redact_text(text: str, secrets=()) -> str:
    result = str(text)
    for secret in secrets:
        if secret:
            result = result.replace(secret, "***")
    return re.sub(
        r"(?i)(Authorization:\s*Bearer\s+|Bearer\s+)\S+",
        r"\1***",
        result,
    )


@dataclass(frozen=True)
class LLMConfig:
    provider_id: str
    api_key: str = field(repr=False)
    base_url: str
    model: str

    def sanitized(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_configured": bool(self.api_key),
        }


@dataclass(frozen=True)
class ChunkingConfig:
    strategy: str = "markdown_heading"
    max_chars: int = 2000


@dataclass(frozen=True)
class PipelineConfig:
    run_name: str
    document_folder: Path
    selected_files: tuple[str, ...]
    llm: LLMConfig
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    retrieve_sentence_num: int = 10
    respect_legacy_breakpoint: bool = False
    reuse_entity_cache: bool = False
    reuse_triplet_cache: bool = False

    def validate(self) -> None:
        if self.llm.provider_id not in PROVIDERS:
            raise ValueError("未知 LLM 提供商")
        if PROVIDERS[self.llm.provider_id].requires_api_key and not self.llm.api_key:
            raise ValueError("当前 LLM 提供商缺少 API Key")
        if not self.llm.base_url.strip():
            raise ValueError("Base URL 不能为空")
        if not self.llm.model.strip():
            raise ValueError("模型名不能为空")
        if not self.selected_files:
            raise ValueError("至少选择一个文档")
        if not 200 <= self.chunking.max_chars <= 20000:
            raise ValueError("切片最大长度必须在 200 到 20000 之间")
        folder = self.document_folder.expanduser().resolve()
        if not folder.is_dir():
            raise ValueError(f"文档文件夹无效：{folder}")
        if any(Path(name).name != name for name in self.selected_files):
            raise ValueError("被选文档必须是输入目录中的文件名")
        for name in self.selected_files:
            path = folder / name
            if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
                raise ValueError(f"被选文档无效：{name}")

    def sanitized_snapshot(self) -> dict:
        return {
            "run_name": self.run_name,
            "document_folder": str(self.document_folder),
            "selected_files": list(self.selected_files),
            "llm": self.llm.sanitized(),
            "chunking": {
                "strategy": self.chunking.strategy,
                "max_chars": self.chunking.max_chars,
            },
            "retrieve_sentence_num": self.retrieve_sentence_num,
            "respect_legacy_breakpoint": self.respect_legacy_breakpoint,
            "reuse_entity_cache": self.reuse_entity_cache,
            "reuse_triplet_cache": self.reuse_triplet_cache,
        }
```

- [ ] **步骤 4：运行测试并确认通过**

运行同一步骤 2。预期：全部 `OK`。

- [ ] **步骤 5：提交**

```powershell
git branch --show-current
git add kg_extract_build/run_config.py kg_extract_build/tests/test_run_config.py
git commit -m "功能：新增实验运行配置和模型提供商预设"
```

预期分支：`feature`。

### 任务 2：支持安全扫描和选择本机文档

**文件：**

- 修改：`kg_extract_build/documents.py`
- 新建：`kg_extract_build/tests/test_document_discovery.py`

- [ ] **步骤 1：先写目录扫描和选择测试**

```python
# kg_extract_build/tests/test_document_discovery.py
import tempfile
import unittest
from pathlib import Path

from kg_extract_build.documents import (
    BreakpointManager,
    DocumentLoader,
    discover_documents,
)


class DocumentDiscoveryTests(unittest.TestCase):
    def test_discovers_only_direct_markdown_and_text_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.txt").write_text("乙", encoding="utf-8")
            (root / "a.md").write_text("甲", encoding="utf-8")
            (root / "skip.pdf").write_bytes(b"pdf")
            (root / "nested").mkdir()
            (root / "nested" / "c.md").write_text("丙", encoding="utf-8")

            files = discover_documents(root)

            self.assertEqual([item.name for item in files], ["a.md", "b.txt"])
            self.assertEqual(files[0].size_bytes, len("甲".encode("utf-8")))

    def test_missing_folder_is_rejected_without_being_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            with self.assertRaisesRegex(ValueError, "不存在"):
                discover_documents(missing)
            self.assertFalse(missing.exists())

    def test_loader_reads_only_selected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("甲", encoding="utf-8")
            (root / "b.md").write_text("乙", encoding="utf-8")
            manager = BreakpointManager(root / "processed.json")
            loader = DocumentLoader(
                root,
                manager,
                respect_breakpoint=False,
                selected_files=("b.md",),
            )

            self.assertEqual(loader.load_all_unprocessed_docs(), {"b.md": "乙"})

    def test_loader_rejects_path_like_selected_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = BreakpointManager(root / "processed.json")
            with self.assertRaisesRegex(ValueError, "文件名"):
                DocumentLoader(root, manager, selected_files=("../outside.md",))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：运行测试并确认失败**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_document_discovery -v
```

预期：失败，原因是 `discover_documents` 和 `selected_files` 尚未实现。

- [ ] **步骤 3：实现只读扫描和选择过滤**

在 `documents.py` 增加：

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscoveredDocument:
    name: str
    extension: str
    size_bytes: int


def discover_documents(folder_path):
    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists():
        raise ValueError(f"文档文件夹不存在：{folder}")
    if not folder.is_dir():
        raise ValueError(f"文档路径不是文件夹：{folder}")
    items = []
    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
            items.append(DiscoveredDocument(path.name, path.suffix.lower(), path.stat().st_size))
    return sorted(items, key=lambda item: item.name.lower())
```

将 `DocumentLoader.__init__` 改为：

```python
def __init__(
    self,
    folder_path,
    breakpoint_manager,
    respect_breakpoint=True,
    selected_files=None,
):
    self.folder_path = Path(folder_path).expanduser().resolve()
    self.breakpoint_manager = breakpoint_manager
    self.respect_breakpoint = respect_breakpoint
    self.selected_files = None if selected_files is None else set(selected_files)
    if not self.folder_path.is_dir():
        raise ValueError(f"文档文件夹无效：{self.folder_path}")
    if self.selected_files is not None:
        for name in self.selected_files:
            if Path(name).name != name:
                raise ValueError(f"只能选择当前目录中的文件名：{name}")
```

在 `load_all_unprocessed_docs()` 的扩展名判断后加入：

```python
if self.selected_files is not None and file_name not in self.selected_files:
    continue
```

删除原有的 `self.folder_path.mkdir(parents=True, exist_ok=True)`，避免把输入错误悄悄变成空目录。

- [ ] **步骤 4：运行新测试和现有测试**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_document_discovery kg_extract_build.tests.test_settings_paths -v
```

预期：全部 `OK`。

- [ ] **步骤 5：提交**

```powershell
git add kg_extract_build/documents.py kg_extract_build/tests/test_document_discovery.py
git commit -m "功能：支持扫描并选择本机文档"
```

### 任务 3：保持默认切片结果并允许调整长度

**文件：**

- 修改：`kg_extract_build/extractor.py`
- 修改：`kg_extract_build/tests/test_chunking.py`

- [ ] **步骤 1：先写默认兼容和自定义长度测试**

在 `ChunkingTests` 中增加：

```python
def test_default_max_chunk_size_remains_2000(self):
    extractor = LongDocLLMEntityExtractor.__new__(LongDocLLMEntityExtractor)
    extractor.max_chunk_size = 2000
    text = "# 标题\n" + ("甲" * 2100)
    chunks = extractor._split_document(text)
    self.assertEqual(len(chunks[0]), 2000)
    self.assertEqual("".join(chunks), text)

def test_custom_max_chunk_size_is_used(self):
    extractor = LongDocLLMEntityExtractor.__new__(LongDocLLMEntityExtractor)
    extractor.max_chunk_size = 500
    text = "甲" * 1200
    self.assertEqual([len(item) for item in extractor._split_document(text)], [500, 500, 200])
```

使用假 OpenAI 客户端补充构造参数测试：

```python
def test_constructor_accepts_custom_max_chunk_size(self):
    class Schema:
        pass

    with mock.patch("kg_extract_build.extractor.OpenAI"):
        extractor = LongDocLLMEntityExtractor([], "key", "url", "model", Schema(), max_chunk_size=800)
    self.assertEqual(extractor.max_chunk_size, 800)
```

并在文件顶部增加 `from unittest import mock`，代码中使用 `mock.patch(...)`。

- [ ] **步骤 2：运行测试并确认构造参数测试失败**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_chunking -v
```

预期：`test_constructor_accepts_custom_max_chunk_size` 因未知参数失败。

- [ ] **步骤 3：给构造函数增加兼容默认值**

```python
def __init__(
    self,
    expert_entities,
    api_key,
    base_url,
    model_name,
    schema,
    max_chunk_size=2000,
):
    self.expert_entities = expert_entities
    self.client = OpenAI(api_key=api_key, base_url=base_url)
    self.model = model_name
    self.schema = schema
    self.max_chunk_size = int(max_chunk_size)
```

不要改动 `_split_document()` 算法，确保 `2000` 时结果与当前版本一致。

- [ ] **步骤 4：运行切片测试并提交**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_chunking -v
git add kg_extract_build/extractor.py kg_extract_build/tests/test_chunking.py
git commit -m "功能：支持调整默认标题切片长度"
```

### 任务 4：实现结构化事件、取消令牌和单任务注册表

**文件：**

- 新建：`kg_extract_build/runtime.py`
- 新建：`kg_extract_build/tests/test_runtime.py`

- [ ] **步骤 1：先写事件、取消和并发保护测试**

```python
# kg_extract_build/tests/test_runtime.py
import threading
import unittest

from kg_extract_build.runtime import (
    CancellationToken,
    PipelineCancelled,
    PipelineEvent,
    PipelineRunRegistry,
    reduce_events,
)


class RuntimeTests(unittest.TestCase):
    def test_cancel_token_raises_pipeline_cancelled(self):
        token = CancellationToken()
        token.cancel()
        with self.assertRaises(PipelineCancelled):
            token.raise_if_cancelled()

    def test_reducer_accumulates_metrics_and_latest_stage(self):
        state = reduce_events(
            {},
            [
                PipelineEvent("document_started", "document", "开始", document_name="a.md"),
                PipelineEvent("chunks_created", "chunking", "切片完成", metrics={"chunks": 3}),
                PipelineEvent("chunks_created", "chunking", "继续切片", metrics={"chunks": 2}),
                PipelineEvent("document_completed", "document", "完成", completed=1, total=2),
            ],
        )
        self.assertEqual(state["stage"], "document")
        self.assertEqual(state["document_name"], "a.md")
        self.assertEqual(state["metrics"]["chunks"], 5)
        self.assertEqual(
            (state["document_completed"], state["document_total"]),
            (1, 2),
        )
        self.assertEqual(state["seen_stages"], ["document", "chunking"])

    def test_registry_rejects_second_active_run_and_can_cancel(self):
        entered = threading.Event()
        release = threading.Event()

        def runner(config, emit, token):
            entered.set()
            release.wait(timeout=2)
            token.raise_if_cancelled()

        registry = PipelineRunRegistry(runner)
        registry.start(object())
        self.assertTrue(entered.wait(timeout=1))
        with self.assertRaisesRegex(RuntimeError, "正在运行"):
            registry.start(object())
        registry.request_cancel()
        release.set()
        registry.join(timeout=2)
        self.assertFalse(registry.is_running)
        self.assertEqual(registry.snapshot()["running"], False)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：运行测试并确认失败**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_runtime -v
```

预期：失败，`kg_extract_build.runtime` 不存在。

- [ ] **步骤 3：实现运行时原语**

```python
# kg_extract_build/runtime.py
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .run_config import redact_text


class PipelineCancelled(RuntimeError):
    pass


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def is_cancelled(self):
        return self._event.is_set()

    def raise_if_cancelled(self):
        if self.is_cancelled:
            raise PipelineCancelled("用户已请求停止实验")


@dataclass(frozen=True)
class PipelineEvent:
    event_type: str
    stage: str
    message: str
    level: str = "info"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    run_id: int | None = None
    document_name: str | None = None
    completed: int | None = None
    total: int | None = None
    metrics: dict = field(default_factory=dict)


def reduce_events(state, events):
    result = {
        "stage": state.get("stage", "idle"),
        "status": state.get("status", "idle"),
        "document_name": state.get("document_name"),
        "metrics": dict(state.get("metrics", {})),
        "events": list(state.get("events", [])),
        "run_id": state.get("run_id"),
        "document_completed": state.get("document_completed", 0),
        "document_total": state.get("document_total", 0),
        "seen_stages": list(state.get("seen_stages", [])),
    }
    for event in events:
        result["stage"] = event.stage
        if event.stage not in result["seen_stages"]:
            result["seen_stages"].append(event.stage)
        if event.document_name is not None:
            result["document_name"] = event.document_name
        if event.run_id is not None:
            result["run_id"] = event.run_id
        if event.event_type == "started" and event.total is not None:
            result["document_total"] = event.total
        if event.event_type in {"document_completed", "document_failed"}:
            if event.completed is not None:
                result["document_completed"] = event.completed
            if event.total is not None:
                result["document_total"] = event.total
        for name, value in event.metrics.items():
            result["metrics"][name] = result["metrics"].get(name, 0) + value
        result["events"].append(event)
        if event.event_type in {"completed", "completed_with_errors", "cancelled", "failed"}:
            result["status"] = event.event_type
        elif event.event_type == "started":
            result["status"] = "running"
    result["events"] = result["events"][-200:]
    return result


class PipelineRunRegistry:
    def __init__(self, runner: Callable):
        self._runner = runner
        self._lock = threading.Lock()
        self._thread = None
        self._token = None
        self._events = queue.Queue()
        self._public_config = None

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, config):
        with self._lock:
            if self.is_running:
                raise RuntimeError("已有实验正在运行")
            self._token = CancellationToken()
            self._events = queue.Queue()
            sanitizer = getattr(config, "sanitized_snapshot", None)
            self._public_config = sanitizer() if sanitizer else {}
            self._thread = threading.Thread(
                target=self._run,
                args=(config, self._token),
                daemon=True,
                name="kg-pipeline-worker",
            )
            self._thread.start()

    def _run(self, config, token):
        try:
            self._runner(config, self._events.put, token)
        except PipelineCancelled:
            self._events.put(PipelineEvent("cancelled", "cancelled", "实验已停止", "warning"))
        except Exception as exc:
            llm = getattr(config, "llm", None)
            secret = getattr(llm, "api_key", "")
            safe_message = redact_text(str(exc), secrets=(secret,))
            self._events.put(PipelineEvent("failed", "failed", safe_message, "error"))

    def request_cancel(self):
        if self._token is not None:
            self._token.cancel()

    def drain_events(self):
        items = []
        while True:
            try:
                items.append(self._events.get_nowait())
            except queue.Empty:
                return items

    def snapshot(self):
        return {
            "running": self.is_running,
            "config": dict(self._public_config or {}),
        }

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)
```

- [ ] **步骤 4：运行测试并确认通过**

运行步骤 2，预期全部 `OK`。

- [ ] **步骤 5：提交**

```powershell
git add kg_extract_build/runtime.py kg_extract_build/tests/test_runtime.py
git commit -m "功能：新增流水线事件和单任务运行注册表"
```

### 任务 5：把配置、事件和安全停止接入流水线

**文件：**

- 修改：`kg_extract_build/run_config.py`
- 修改：`kg_extract_build/pipeline.py`
- 修改：`kg_extract_build/extractor.py`
- 修改：`kg_extract_build/entity_aligner.py`
- 修改：`kg_extract_build/triplets.py`
- 修改：`kg_extract_build/persistence.py`
- 修改：`kg_extract_build/tests/test_experiment_tracking.py`
- 新建：`kg_extract_build/tests/test_pipeline_control.py`

- [ ] **步骤 1：先写抽取器和对齐器取消边界测试**

```python
# kg_extract_build/tests/test_pipeline_control.py
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kg_extract_build.entity_aligner import EntityAligner
from kg_extract_build.extractor import LongDocLLMEntityExtractor
from kg_extract_build.persistence import MemoryExperimentStore
from kg_extract_build.pipeline import run_pipeline
from kg_extract_build.run_config import ChunkingConfig, LLMConfig, PipelineConfig
from kg_extract_build.runtime import CancellationToken, PipelineCancelled, PipelineEvent
from kg_extract_build.vector_store import NullVectorStore


class Schema:
    schema_path = Path("schema.json")
    entity_types = {}
    relation_types = {}

    def normalize_entity_type(self, value):
        return value

    def render_entity_schema(self):
        return "设施"


class PipelineControlTests(unittest.TestCase):
    def test_extractor_stops_before_first_chunk_request(self):
        token = CancellationToken()
        token.cancel()
        extractor = LongDocLLMEntityExtractor.__new__(LongDocLLMEntityExtractor)
        extractor.max_chunk_size = 2000
        extractor.expert_entities = []
        extractor.schema = Schema()
        with self.assertRaises(PipelineCancelled):
            extractor.extract("# 标题\n内容", cancel_token=token)

    def test_aligner_stops_between_candidate_groups(self):
        token = CancellationToken()
        token.cancel()
        aligner = EntityAligner.__new__(EntityAligner)
        aligner._deduplicate_entities = lambda entities, source_type: entities
        aligner._build_candidate_groups = lambda entities: [[entities[0], entities[1]]]
        with self.assertRaises(PipelineCancelled):
            aligner.align(
                [{"name": "井口", "type": "设施"}, {"name": "井口装置", "type": "设施"}],
                cancel_token=token,
            )

    def test_pipeline_event_never_contains_api_key(self):
        event = PipelineEvent("started", "run", "开始")
        self.assertNotIn("api_key", event.__dict__)

    def test_extractor_redacts_secret_from_recorded_error(self):
        class FailingCompletions:
            def create(self, **kwargs):
                raise RuntimeError("Authorization: Bearer top-secret")

        class Recorder:
            def __init__(self):
                self.error_message = ""

            def record_llm_call(self, **kwargs):
                self.error_message = kwargs["error_message"]

        extractor = LongDocLLMEntityExtractor.__new__(LongDocLLMEntityExtractor)
        extractor.client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": FailingCompletions()})()},
        )()
        extractor.model = "model"
        extractor.schema = Schema()
        extractor._secret_values = ("top-secret",)
        recorder = Recorder()
        extractor._extract_from_chunk("内容", recorder=recorder, chunk_index=0)
        self.assertNotIn("top-secret", recorder.error_message)

    def test_cancelled_pipeline_persists_cancelled_status_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("# 标题\n内容", encoding="utf-8")
            config = PipelineConfig(
                run_name="取消测试",
                document_folder=root,
                selected_files=("a.md",),
                llm=LLMConfig(
                    "ollama",
                    "ollama",
                    "http://localhost:11434/v1/",
                    "qwen3",
                ),
                chunking=ChunkingConfig(),
            )
            store = MemoryExperimentStore()
            token = CancellationToken()
            token.cancel()
            events = []
            with (
                patch("kg_extract_build.pipeline.KGSchema", return_value=Schema()),
                patch("kg_extract_build.pipeline.build_experiment_store", return_value=store),
                patch("kg_extract_build.pipeline.build_vector_store", return_value=NullVectorStore()),
                patch("kg_extract_build.pipeline.current_code_commit", return_value="commit"),
            ):
                run_id = run_pipeline(config, events.append, token)

        self.assertEqual(store.runs[run_id]["status"], "cancelled")
        self.assertEqual([event.event_type for event in events], ["started", "cancelled"])
        self.assertNotIn("api_key", repr(store.runs[run_id]["config_snapshot"]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：运行测试并确认签名失败**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_pipeline_control -v
```

预期：`extract()` 和 `align()` 不接受 `cancel_token`。

在 `test_experiment_tracking.py` 增加：

```python
def test_reports_each_persisted_llm_call_to_callback(self):
    store = MemoryExperimentStore()
    run_id = store.start_run("test", {}, {}, "")
    document_id = store.start_document(run_id, "doc.md", "case", "abc", "text")
    callbacks = []
    recorder = ExperimentRecorder(
        store,
        FakeVectorStore(),
        run_id,
        document_id,
        model_name="model",
        event_callback=callbacks.append,
    )
    recorder.record_llm_call(stage="entity_extraction", prompt="prompt")
    self.assertEqual(callbacks, [{"stage": "entity_extraction", "success": True}])
```

再次运行：

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_experiment_tracking -v
```

预期：`ExperimentRecorder.__init__()` 不接受 `event_callback`。

- [ ] **步骤 3：在内部 LLM 循环加入取消检查和进度回调**

将抽取器签名改为：

```python
def extract(self, full_text, recorder=None, cancel_token=None, progress_callback=None):
    chunks = self._split_document(full_text)
    if recorder is not None:
        recorder.record_chunks("entity_extraction", chunks)
    all_entities = []
    for index, chunk in enumerate(chunks, start=1):
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        all_entities.extend(
            self._extract_from_chunk(chunk, recorder=recorder, chunk_index=index - 1)
        )
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if progress_callback is not None:
            progress_callback(index, len(chunks))
```

上述改动只替换现有 `extract()` 中从 `chunks = ...` 到切片循环结束的部分；循环之后的 `_extract_normative_entities()`、`_filter_invalid_entities()`、实体去重、排序和返回语句原样保留。

将对齐器签名和候选组循环改为：

```python
def align(
    self,
    entities,
    source_type="case",
    recorder=None,
    cancel_token=None,
    progress_callback=None,
):
    for index, group in enumerate(candidate_groups, start=1):
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if len(group) <= 1:
            continue
        decision = self._judge_group(group, recorder=recorder)
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        if progress_callback is not None:
            progress_callback(index, len(candidate_groups))
```

只修改 `align()` 的函数签名，并在现有 `for group in candidate_groups` 循环中加入索引、取消检查和回调；原有 `same_groups`、`alias_to_standard`、`consumed` 及未消费实体处理逻辑不移动。

同时在三个 LLM 组件中保存只用于脱敏的私有值：

```python
self._secret_values = (api_key,)
```

`extractor.py`、`entity_aligner.py` 和 `triplets.py` 的每个 `except Exception as exc` 分支统一改为：

```python
safe_error = redact_text(str(exc), secrets=self._secret_values)
print(f"LLM 调用失败：{safe_error}")
```

传给 `recorder.record_llm_call(error_message=...)` 的值必须使用 `safe_error`，不得继续使用 `str(exc)`。三个模块均从 `kg_extract_build.run_config` 导入 `redact_text`。

- [ ] **步骤 4：扩充 `PipelineConfig.from_settings()`，保持命令行兼容**

在 `run_config.py` 中增加静态路径和存储开关字段，并实现：

```python
@classmethod
def from_settings(cls):
    from . import settings

    provider_id = os.getenv("LLM_PROVIDER", "zhipu")
    return cls(
        run_name=settings.EXPERIMENT_RUN_NAME or "",
        document_folder=settings.DOCUMENT_FOLDER,
        selected_files=tuple(),
        llm=LLMConfig(
            provider_id=provider_id,
            api_key=resolve_provider_api_key(provider_id),
        base_url=os.getenv(
            "LLM_BASE_URL",
            PROVIDERS[provider_id].default_base_url,
        ),
            model=settings.LLM_MODEL,
        ),
        chunking=ChunkingConfig(),
        retrieve_sentence_num=settings.RETRIEVE_SENTENCE_NUM,
        respect_legacy_breakpoint=settings.RESPECT_LEGACY_BREAKPOINT,
        reuse_entity_cache=settings.REUSE_ENTITY_CACHE,
        reuse_triplet_cache=settings.REUSE_TRIPLET_CACHE,
    )
```

命令行模式在扫描后补全全部符合条件的 `selected_files`；界面模式必须使用用户明确选择的文件。

- [ ] **步骤 5：重构 `run_pipeline` 并发出事件**

在 `pipeline.py` 增加：

```python
from .run_config import PipelineConfig, redact_text
from .runtime import CancellationToken, PipelineCancelled, PipelineEvent
```

将入口改为：

```python
def run_pipeline(config=None, emit=None, cancel_token=None):
    if config is None:
        from dataclasses import replace
        from .documents import discover_documents

        config = PipelineConfig.from_settings()
        discovered = discover_documents(config.document_folder)
        config = replace(
            config,
            selected_files=tuple(item.name for item in discovered),
        )
    config.validate()
    cancel_token = cancel_token or CancellationToken()

    def publish(event_type, stage, message, **kwargs):
        event = PipelineEvent(event_type, stage, message, **kwargs)
        if emit is not None:
            emit(event)
        return event
```

随后逐项替换全局运行参数：

```python
doc_loader = DocumentLoader(
    config.document_folder,
    breakpoint_manager,
    respect_breakpoint=config.respect_legacy_breakpoint,
    selected_files=config.selected_files or None,
)
extractor = LongDocLLMEntityExtractor(
    EXPERT_ENTITIES,
    config.llm.api_key,
    config.llm.base_url,
    config.llm.model,
    schema,
    max_chunk_size=config.chunking.max_chars,
)
aligner = EntityAligner(
    config.llm.api_key,
    config.llm.base_url,
    config.llm.model,
    VECTOR_MODEL_PATH,
)
```

创建实验时使用：

```python
run_id = store.start_run(
    config.run_name or default_run_name(),
    {
        **config.sanitized_snapshot(),
        "schema_path": str(resolve_schema_path()),
        "vector_model_path": str(VECTOR_MODEL_PATH),
        "mysql_enabled": MYSQL_ENABLED,
        "milvus_enabled": MILVUS_ENABLED,
    },
    schema_snapshot(schema),
    current_code_commit(),
)
publish("started", "run", "实验已开始", run_id=run_id, total=len(docs))
```

在文档、切片、实体和三元组循环边界调用：

```python
cancel_token.raise_if_cancelled()
```

为抽取器和对齐器传入回调：

```python
entities = extractor.extract(
    content,
    recorder=recorder,
    cancel_token=cancel_token,
    progress_callback=lambda completed, total: publish(
        "chunk_progress",
        "entity_extraction",
        f"实体抽取切片 {completed}/{total}",
        document_name=file_name,
        completed=completed,
        total=total,
    ),
)
```

对齐阶段使用对应回调：

```python
entities, alias_to_standard = aligner.align(
    entities,
    source_type=source_type,
    recorder=recorder,
    cancel_token=cancel_token,
    progress_callback=lambda completed, total: publish(
        "alignment_progress",
        "entity_alignment",
        f"实体对齐候选组 {completed}/{total}",
        document_name=file_name,
        completed=completed,
        total=total,
    ),
)
```

在记录切片、对齐实体和最终三元组后分别发送指标事件：

```python
publish(
    "chunks_created",
    "chunking",
    f"已保存 {len(retriever.sentences)} 个检索切片",
    document_name=file_name,
    metrics={"chunks": len(retriever.sentences)},
)
publish(
    "entities_aligned",
    "entity_alignment",
    f"获得 {len(entities)} 个对齐实体",
    document_name=file_name,
    metrics={"entities": len(entities)},
)
publish(
    "triplets_completed",
    "triplet_correction",
    f"获得 {len(clean_triplets)} 个最终三元组",
    document_name=file_name,
    metrics={"triplets": len(clean_triplets)},
)
```

每次 `retrieve_entity_context()` 返回后发送检索阶段事件：

```python
publish(
    "retrieval_completed",
    "retrieval",
    f"已完成实体上下文检索：{entity['name']}",
    document_name=file_name,
)
```

每篇文档成功或空结果结束后累计文档进度：

```python
completed_documents += 1
publish(
    "document_completed",
    "document",
    f"文档处理完成：{file_name}",
    document_name=file_name,
    completed=completed_documents,
    total=len(docs),
    metrics={"documents": 1},
)
```

单篇文档失败时也累计已经处理的文档数，但不计入成功文档指标：

```python
failed_documents += 1
completed_documents += 1
safe_error = redact_text(str(exc), secrets=(config.llm.api_key,))
store.finish_document(document_id, "failed", safe_error)
publish(
    "document_failed",
    "document",
    f"文档处理失败：{file_name}：{safe_error}",
    level="error",
    document_name=file_name,
    completed=completed_documents,
    total=len(docs),
)
```

在单文档异常处理前增加取消分支：

```python
except PipelineCancelled:
    store.finish_document(document_id, "cancelled", "用户停止实验")
    raise
```

每个实体的三元组请求前继续检查 `cancel_token`，并在调用 `corrector.correct(raw_triplets)` 前再检查一次，确保最后一个 LLM 请求返回后也能停止：

```python
for entity in entities:
    cancel_token.raise_if_cancelled()
    saved_triplets = None

cancel_token.raise_if_cancelled()
clean_triplets = corrector.correct(raw_triplets)
```

取消检查插入现有实体循环的第一行；其后的缓存读取、`retrieve_entity_context()` 和 `generator.generate()` 代码保持原顺序。

在顶层 `except Exception` 前增加：

```python
except PipelineCancelled:
    if run_id is not None:
        store.finish_run(run_id, "cancelled")
    publish("cancelled", "cancelled", "实验已安全停止", level="warning", run_id=run_id)
    return run_id
```

成功结束时使用：

```python
run_status = "completed_with_errors" if failed_documents else "completed"
store.finish_run(run_id, run_status)
publish(
    run_status,
    "completed",
    "实验完成，但部分文档失败" if failed_documents else "实验运行完成",
    level="warning" if failed_documents else "success",
    run_id=run_id,
)
return run_id
```

所有事件只能传递 `PipelineEvent` 允许字段，不传入配置对象和异常对象。

普通异常写入数据库或事件前统一调用：

```python
safe_error = redact_text(str(exc), secrets=(config.llm.api_key,))
```

- [ ] **步骤 6：让 recorder 报告 LLM 调用计数**

将 `ExperimentRecorder.__init__` 改为：

```python
def __init__(
    self,
    store,
    vector_store,
    run_id,
    document_id,
    model_name="",
    event_callback=None,
):
    self.store = store
    self.vector_store = vector_store
    self.run_id = run_id
    self.document_id = document_id
    self.model_name = model_name
    self.event_callback = event_callback
    self._chunk_ids = {}
```

将 `record_llm_call()` 的直接返回改为：

```python
call_id = self.store.save_llm_call(
    run_id=self.run_id,
    document_id=self.document_id,
    chunk_id=chunk_id,
    stage=stage,
    entity_name=entity_name,
    model_name=self.model_name,
    prompt=prompt,
    raw_response=raw_response,
    parsed_result=parsed,
    metadata=metadata,
    latency_ms=latency_ms,
    success=success,
    error_message=error_message,
)
if self.event_callback is not None:
    self.event_callback({"stage": stage, "success": success})
return call_id
```

流水线创建 recorder 时传入：

```python
recorder = ExperimentRecorder(
    store,
    vector_store,
    run_id,
    document_id,
    model_name=config.llm.model,
    event_callback=lambda item: publish(
        "llm_call",
        item["stage"],
        f"LLM 调用完成：{item['stage']}",
        level="info" if item["success"] else "warning",
        document_name=file_name,
        metrics={"llm_calls": 1},
    ),
)
```

- [ ] **步骤 7：运行控制测试和完整回归测试**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_pipeline_control -v
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest discover -s kg_extract_build/tests -v
```

预期：全部 `OK`，原有切片、持久化和检索测试不回归。

- [ ] **步骤 8：提交**

```powershell
git add kg_extract_build/run_config.py kg_extract_build/pipeline.py kg_extract_build/extractor.py kg_extract_build/entity_aligner.py kg_extract_build/triplets.py kg_extract_build/persistence.py kg_extract_build/tests/test_pipeline_control.py kg_extract_build/tests/test_experiment_tracking.py
git commit -m "重构：接入可配置流水线和安全停止"
```

### 任务 6：实现运行实验页面和默认切片提示

**文件：**

- 新建：`kg_extract_build/dashboard_run.py`
- 新建：`kg_extract_build/tests/test_dashboard_run.py`
- 新建：`kg_extract_build/tests/test_dashboard_smoke.py`
- 修改：`kg_extract_build/dashboard.py`

- [ ] **步骤 1：先写默认切片提示和状态归并测试**

```python
# kg_extract_build/tests/test_dashboard_run.py
import unittest

from kg_extract_build.dashboard_run import chunking_notice, provider_form_defaults


class DashboardRunTests(unittest.TestCase):
    def test_default_chunking_notice_is_explicit(self):
        level, message = chunking_notice(2000)
        self.assertEqual(level, "info")
        self.assertIn("当前使用项目默认切片配置", message)
        self.assertIn("2000", message)

    def test_custom_chunking_notice_shows_actual_value(self):
        level, message = chunking_notice(1200)
        self.assertEqual(level, "warning")
        self.assertIn("自定义配置", message)
        self.assertIn("1200", message)

    def test_provider_defaults_do_not_return_secret(self):
        defaults = provider_form_defaults("deepseek")
        self.assertNotIn("api_key", defaults)
        self.assertEqual(defaults["base_url"], "https://api.deepseek.com")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：运行测试并确认模块不存在**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_dashboard_run -v
```

预期：`ModuleNotFoundError`。

- [ ] **步骤 3：实现可测试辅助函数和运行注册表资源**

```python
# kg_extract_build/dashboard_run.py
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from kg_extract_build.documents import discover_documents
from kg_extract_build.pipeline import run_pipeline
from kg_extract_build.run_config import (
    ChunkingConfig,
    LLMConfig,
    PipelineConfig,
    PROVIDERS,
    resolve_provider_api_key,
)
from kg_extract_build.runtime import PipelineRunRegistry, reduce_events


def chunking_notice(max_chars):
    if int(max_chars) == 2000:
        return (
            "info",
            "当前使用项目默认切片配置：Markdown 标题感知，最大长度 2000 字符",
        )
    return (
        "warning",
        f"当前已调整切片长度，本次实验将使用自定义配置：最大长度 {int(max_chars)} 字符",
    )


def provider_form_defaults(provider_id):
    preset = PROVIDERS[provider_id]
    return {
        "label": preset.label,
        "base_url": preset.default_base_url,
        "requires_api_key": preset.requires_api_key,
        "environment_configured": bool(resolve_provider_api_key(provider_id)),
    }


@st.cache_resource
def get_run_registry():
    return PipelineRunRegistry(run_pipeline)
```

- [ ] **步骤 4：实现左侧配置与文件预览**

在 `render_run_page()` 中使用两列布局：

```python
def render_run_page():
    st.markdown('<div class="kg-eyebrow">KG Experiment Console</div>', unsafe_allow_html=True)
    st.title("运行实体提取实验")
    st.caption("配置本次实验并实时查看切片、实体、检索和三元组生成过程。")

    config_col, monitor_col = st.columns([0.36, 0.64], gap="large")
    registry = get_run_registry()

    with config_col:
        run_name = st.text_input(
            "实验名称",
            value=datetime.now().strftime("kg-run-%Y%m%d-%H%M%S"),
            disabled=registry.is_running,
        )
        folder_text = st.text_input(
            "本机文档文件夹",
            value=os.getenv("KG_DOCUMENT_FOLDER", ""),
            disabled=registry.is_running,
        )
        documents = []
        if folder_text.strip():
            try:
                documents = discover_documents(Path(folder_text))
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"文件名": item.name, "类型": item.extension, "大小（字节）": item.size_bytes}
                            for item in documents
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
            except ValueError as exc:
                st.warning(str(exc))
        selected_files = st.multiselect(
            "选择本次处理的文件",
            [item.name for item in documents],
            default=[item.name for item in documents],
            disabled=registry.is_running,
        )
```

提供商切换后，Base URL 使用提供商专属 widget key，保证默认地址同步变化：

```python
provider_id = st.selectbox(
    "LLM 提供商",
    list(PROVIDERS),
    format_func=lambda value: PROVIDERS[value].label,
    disabled=registry.is_running,
)
preset = provider_form_defaults(provider_id)
base_url = st.text_input(
    "Base URL",
    value=preset["base_url"],
    key=f"llm_base_url_{provider_id}",
    disabled=registry.is_running,
)
model = st.text_input(
    "模型名称",
    value=os.getenv("LLM_MODEL", ""),
    key=f"llm_model_{provider_id}",
    disabled=registry.is_running,
)
api_key_override = st.text_input(
    "API Key（仅本次会话临时覆盖）",
    value="",
    type="password",
    key=f"llm_api_key_{provider_id}",
    disabled=registry.is_running,
)
if preset["environment_configured"]:
    st.caption("已从对应环境变量读取凭据；临时输入将优先使用。")
```

切片和高级参数使用：

```python
max_chars = st.number_input(
    "切片最大长度（字符）",
    min_value=200,
    max_value=20000,
    value=2000,
    step=100,
    disabled=registry.is_running,
)
notice_level, notice_text = chunking_notice(max_chars)
getattr(st, notice_level)(notice_text)
with st.expander("高级参数"):
    retrieve_count = st.number_input(
        "每个实体检索句数",
        min_value=1,
        max_value=100,
        value=10,
        disabled=registry.is_running,
    )
    respect_breakpoint = st.checkbox(
        "跳过断点记录中的已处理文件",
        value=False,
        disabled=registry.is_running,
    )
    reuse_entity_cache = st.checkbox(
        "复用实体对齐缓存",
        value=False,
        disabled=registry.is_running,
    )
    reuse_triplet_cache = st.checkbox(
        "复用三元组缓存",
        value=False,
        disabled=registry.is_running,
    )
```

开始按钮点击后才构造并启动配置：

```python
start_col, stop_col = st.columns(2)
with start_col:
    start_clicked = st.button(
        "开始运行",
        type="primary",
        use_container_width=True,
        disabled=registry.is_running,
    )
with stop_col:
    stop_clicked = st.button(
        "停止实验",
        use_container_width=True,
        disabled=not registry.is_running,
    )
if stop_clicked:
    registry.request_cancel()
    st.warning("已请求停止，将在当前请求结束后的安全边界停止。")

if start_clicked:
    try:
        api_key = resolve_provider_api_key(provider_id, api_key_override)
        config = PipelineConfig(
            run_name=run_name.strip(),
            document_folder=Path(folder_text),
            selected_files=tuple(selected_files),
            llm=LLMConfig(provider_id, api_key, base_url.strip(), model.strip()),
            chunking=ChunkingConfig(max_chars=int(max_chars)),
            retrieve_sentence_num=int(retrieve_count),
            respect_legacy_breakpoint=respect_breakpoint,
            reuse_entity_cache=reuse_entity_cache,
            reuse_triplet_cache=reuse_triplet_cache,
        )
        config.validate()
        registry.start(config)
        st.session_state["pipeline_view_state"] = {}
        st.rerun()
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc))
```

- [ ] **步骤 5：实现运行、停止和实时监控**

使用 Streamlit fragment 每秒消费事件：

```python
def render_monitor_body(registry):
    events = registry.drain_events()
    state = reduce_events(st.session_state.get("pipeline_view_state", {}), events)
    st.session_state["pipeline_view_state"] = state
    metrics = state.get("metrics", {})
    columns = st.columns(5)
    columns[0].metric("文档", metrics.get("documents", 0))
    columns[1].metric("切片", metrics.get("chunks", 0))
    columns[2].metric("实体", metrics.get("entities", 0))
    columns[3].metric("LLM 调用", metrics.get("llm_calls", 0))
    columns[4].metric("三元组", metrics.get("triplets", 0))
    completed = state.get("document_completed") or 0
    total = state.get("document_total") or 0
    st.progress(completed / total if total else 0.0, text=f"文档进度：{completed}/{total}")
    st.write(f"当前阶段：{state.get('stage', '等待开始')}")
    st.write(f"当前文档：{state.get('document_name') or '—'}")
    stage_labels = [
        ("document", "文档"),
        ("chunking", "切片"),
        ("entity_extraction", "实体抽取"),
        ("entity_alignment", "实体对齐"),
        ("retrieval", "语义检索"),
        ("triplet_extraction", "三元组生成"),
        ("triplet_correction", "校正"),
        ("completed", "完成"),
    ]
    seen_stages = set(state.get("seen_stages", []))
    st.caption(
        " → ".join(
            f"{'✅' if stage in seen_stages else '○'} {label}"
            for stage, label in stage_labels
        )
    )
    status = state.get("status", "idle")
    status_renderers = {
        "running": (st.info, "实验正在运行"),
        "completed": (st.success, "实验运行完成"),
        "completed_with_errors": (st.warning, "实验完成，但部分文档失败"),
        "cancelled": (st.warning, "实验已安全停止"),
        "failed": (st.error, "实验运行失败"),
    }
    if status in status_renderers:
        renderer, text = status_renderers[status]
        renderer(text)
    for event in reversed(state.get("events", [])[-50:]):
        st.caption(f"{event.timestamp} · {event.message}")
    if state.get("run_id") is not None:
        st.success(f"实验 run_id：{state['run_id']}")
        if st.button("查看本次实验", key=f"inspect_run_{state['run_id']}"):
            st.session_state["preferred_run_id"] = state["run_id"]
            st.session_state["requested_navigation_page"] = "实验批次"
            st.rerun(scope="app")
    return bool(events)


@st.fragment(run_every=1.0)
def render_active_monitor(registry):
    had_events = render_monitor_body(registry)
    if not registry.is_running and had_events:
        st.rerun(scope="app")
```

在 `monitor_col` 中按运行状态调用，避免实验结束后继续轮询：

```python
with monitor_col:
    if registry.is_running:
        render_active_monitor(registry)
    else:
        render_monitor_body(registry)
```

- [ ] **步骤 6：把运行页面设为默认导航**

在 `dashboard.py` 底部改为：

```python
from kg_extract_build.dashboard_run import render_run_page

requested_page = st.session_state.pop("requested_navigation_page", None)
if requested_page is not None:
    st.session_state["navigation_page"] = requested_page

page = st.sidebar.radio(
    "导航",
    ["运行实验", "实验总览", "实验批次", "文档追踪", "LLM 调用", "知识图谱"],
    key="navigation_page",
)

if page == "运行实验":
    render_run_page()
else:
    config = connection_config()
    try:
        with st.spinner("正在读取实验数据库…"):
            if page == "实验总览":
                overview_page(config)
            elif page == "实验批次":
                runs_page(config)
            elif page == "文档追踪":
                documents_page(config)
            elif page == "LLM 调用":
                llm_page(config)
            else:
                graph_page(config)
    except Exception as exc:
        setup_help()
        with st.expander("错误详情"):
            st.code(str(exc), language="text")
```

在现有 `choose_run()` 中，根据 `preferred_run_id` 设置默认索引：

```python
run_ids = list(labels)
preferred = st.session_state.get("preferred_run_id")
default_index = run_ids.index(preferred) if preferred in run_ids else 0
selected = st.selectbox(
    "实验批次",
    options=run_ids,
    index=default_index,
    format_func=lambda value: labels[value],
    key=key,
)
```

该代码替换原 `choose_run()` 中对应的 `st.selectbox` 调用。

`dashboard_run.py` 和 `dashboard.py` 新增的跨模块引用统一使用 `from kg_extract_build...` 绝对导入，启动命令固定为 `python -m streamlit run kg_extract_build/dashboard.py`。

- [ ] **步骤 7：运行界面辅助测试和完整回归**

先增加应用级冒烟测试：

```python
# kg_extract_build/tests/test_dashboard_smoke.py
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class DashboardSmokeTests(unittest.TestCase):
    def test_default_run_page_starts_without_mysql_connection(self):
        dashboard = Path(__file__).resolve().parents[1] / "dashboard.py"
        app = AppTest.from_file(str(dashboard)).run(timeout=15)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(any(title.value == "运行实体提取实验" for title in app.title))


if __name__ == "__main__":
    unittest.main()
```

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_dashboard_run -v
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_dashboard_smoke -v
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest discover -s kg_extract_build/tests -v
```

预期：全部 `OK`。

- [ ] **步骤 8：提交**

```powershell
git add kg_extract_build/dashboard_run.py kg_extract_build/dashboard.py kg_extract_build/tests/test_dashboard_run.py kg_extract_build/tests/test_dashboard_smoke.py
git commit -m "功能：新增可视化实验运行控制台"
```

### 任务 7：更新环境变量示例和中文使用文档

**文件：**

- 修改：`kg_extract_build/.env.example`
- 修改：`kg_extract_build/README.md`
- 修改：`README.md`

- [ ] **步骤 1：先写文档配置检查测试**

新建 `kg_extract_build/tests/test_provider_docs.py`：

```python
import unittest
from pathlib import Path


class ProviderDocsTests(unittest.TestCase):
    def test_env_example_lists_all_online_provider_credentials(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / ".env.example").read_text(encoding="utf-8")
        for name in [
            "ZAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "DASHSCOPE_API_KEY",
            "MODELSCOPE_API_TOKEN",
            "HF_TOKEN",
        ]:
            self.assertIn(name, text)

    def test_readme_uses_single_streamlit_start_command(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "python -m streamlit run kg_extract_build/dashboard.py",
            text,
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：运行测试并确认缺少变量时失败**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_provider_docs -v
```

预期：至少一个提供商变量断言失败。

- [ ] **步骤 3：补充 `.env.example`**

加入：

```dotenv
# LLM 提供商；可选 zhipu/deepseek/ollama/qwen/modelscope/huggingface/custom
LLM_PROVIDER=zhipu
LLM_MODEL=glm-4.5-air
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/

# 按实际使用的平台填写；不要提交真实密钥
ZAI_API_KEY=
DEEPSEEK_API_KEY=
DASHSCOPE_API_KEY=
MODELSCOPE_API_TOKEN=
HF_TOKEN=
LLM_API_KEY=
```

保留现有 MySQL、Milvus 和路径配置，不重复定义。

- [ ] **步骤 4：更新中文启动说明**

文档明确：

```powershell
conda activate env_agent
cd D:\ProgramData\PythonProject\NLPTest\AgentTest\github_kg_extract_build
python -m streamlit run kg_extract_build/dashboard.py
```

说明无需再单独执行 pipeline；在“运行实验”页面选择路径、文件、提供商、模型和切片长度即可。注明 API Key 的 `.env` 优先级、界面临时覆盖规则、默认切片提示和安全停止语义。

- [ ] **步骤 5：运行测试并提交**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest kg_extract_build.tests.test_provider_docs -v
git add kg_extract_build/.env.example kg_extract_build/README.md README.md kg_extract_build/tests/test_provider_docs.py
git commit -m "文档：补充可视化运行和模型提供商配置"
```

### 任务 8：完整验证和交付检查

**文件：**

- 检查：`kg_extract_build/`
- 检查：`docs/superpowers/specs/2026-07-02-streamlit-pipeline-console-design.md`
- 检查：`docs/superpowers/plans/2026-07-02-streamlit-pipeline-console-plan.md`

- [ ] **步骤 1：确认分支和工作区**

```powershell
git branch --show-current
git status --short
```

预期：分支为 `feature`；只存在本轮尚未提交的预期改动。

- [ ] **步骤 2：运行完整测试**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m unittest discover -s kg_extract_build/tests -v
```

预期：全部测试为 `OK`，无失败和错误。

- [ ] **步骤 3：运行编译和差异检查**

```powershell
& D:\ProgramData\anaconda3\envs\env_agent\python.exe -m compileall -q kg_extract_build
git diff --check
```

预期：两个命令退出码均为 `0`；只允许出现 Git 的 LF/CRLF 提示，不允许空白错误。

- [ ] **步骤 4：执行 Streamlit 无界面启动冒烟测试**

```powershell
$python = 'D:\ProgramData\anaconda3\envs\env_agent\python.exe'
$process = Start-Process `
  -FilePath $python `
  -ArgumentList '-m','streamlit','run','kg_extract_build/dashboard.py','--server.headless=true','--server.port=8765' `
  -WindowStyle Hidden `
  -PassThru
try {
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765 -TimeoutSec 1
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Streamlit 未在 15 秒内就绪' }
} finally {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
```

预期：HTTP 状态为 `200`，脚本无异常退出。

- [ ] **步骤 5：执行安全性检查**

```powershell
rg -n "api_key.*snapshot|api_key.*event|st\\.text_input\\(.*API Key" kg_extract_build
rg -n "ZAI_API_KEY=.+|DEEPSEEK_API_KEY=.+|DASHSCOPE_API_KEY=.+|HF_TOKEN=.+" .
```

人工确认：

- API Key 控件使用 `type="password"`；
- `sanitized_snapshot()` 不返回密钥；
- 事件不接受配置字典；
- `.env` 仍由 `.gitignore` 排除；
- 示例配置中没有真实密钥。

- [ ] **步骤 6：逐条核对验收标准**

确认：

1. 只需启动 Streamlit；
2. 可以扫描、预览并选择文件；
3. 七种提供商均可选择；
4. 密钥不持久化；
5. `2000` 时界面显示默认切片配置提示；
6. 自定义长度时显示自定义配置提示；
7. 进度、事件和指标实时显示；
8. 停止后状态为 `cancelled`；
9. 历史看板仍可使用。

- [ ] **步骤 7：提交验证期间必要修复**

若步骤 2–6 发现问题，必须先新增能复现问题的失败测试，再修复并重新运行全部验证。修复提交信息使用：

```powershell
git commit -m "修复：完善可视化流水线交付检查"
```

若没有产生代码改动，不创建空提交。
