"""Safe, serializable configuration for knowledge-graph experiment runs."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional for library consumers.
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv(Path(__file__).with_name(".env"), override=False)


@dataclass(frozen=True)
class ProviderPreset:
    provider_id: str
    label: str
    default_base_url: str
    env_keys: tuple[str, ...]
    requires_api_key: bool = True


PROVIDERS: dict[str, ProviderPreset] = {
    "zhipu": ProviderPreset(
        provider_id="zhipu",
        label="智谱",
        default_base_url="https://open.bigmodel.cn/api/paas/v4/",
        env_keys=("ZAI_API_KEY", "LLM_API_KEY"),
    ),
    "deepseek": ProviderPreset(
        provider_id="deepseek",
        label="DeepSeek",
        default_base_url="https://api.deepseek.com",
        env_keys=("DEEPSEEK_API_KEY", "LLM_API_KEY"),
    ),
    "ollama": ProviderPreset(
        provider_id="ollama",
        label="Ollama",
        default_base_url="http://localhost:11434/v1/",
        env_keys=(),
        requires_api_key=False,
    ),
    "qwen": ProviderPreset(
        provider_id="qwen",
        label="Qwen / 阿里云百炼",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        env_keys=("DASHSCOPE_API_KEY",),
    ),
    "modelscope": ProviderPreset(
        provider_id="modelscope",
        label="ModelScope / 魔搭",
        default_base_url="",
        env_keys=("MODELSCOPE_API_TOKEN",),
    ),
    "huggingface": ProviderPreset(
        provider_id="huggingface",
        label="Hugging Face",
        default_base_url="https://router.huggingface.co/v1",
        env_keys=("HF_TOKEN",),
    ),
    "custom": ProviderPreset(
        provider_id="custom",
        label="本地 / 自定义 OpenAI 兼容接口",
        default_base_url=os.environ.get("LLM_BASE_URL", ""),
        env_keys=("LLM_API_KEY",),
    ),
}


def _provider(provider_id: str) -> ProviderPreset:
    try:
        return PROVIDERS[provider_id]
    except KeyError as exc:
        raise ValueError(f"未知的 LLM 提供商：{provider_id}") from exc


def resolve_provider_api_key(
    provider_id: str,
    override: str = "",
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve an API key without persisting a UI-provided override."""

    preset = _provider(provider_id)
    if override.strip():
        return override.strip()

    source = os.environ if environ is None else environ
    for key in preset.env_keys:
        value = source.get(key, "").strip()
        if value:
            return value

    return "ollama" if provider_id == "ollama" else ""


def redact_text(text: str, secrets: Sequence[str] = ()) -> str:
    """Remove known secrets and bearer credentials from diagnostic text."""

    redacted = str(text)
    known_secrets = sorted(
        (str(secret) for secret in secrets if secret),
        key=len,
        reverse=True,
    )
    for secret in known_secrets:
        redacted = redacted.replace(secret, "***")
    return re.sub(
        r"(?i)\bBearer\s+[^\s,;]+",
        "Bearer ***",
        redacted,
    )


@dataclass(frozen=True)
class LLMConfig:
    provider_id: str
    api_key: str = field(repr=False)
    base_url: str
    model: str

    def sanitized(self) -> dict[str, object]:
        secret = (self.api_key,) if self.api_key else ()
        return {
            "provider_id": self.provider_id,
            "base_url": redact_text(self.base_url, secrets=secret),
            "model": redact_text(self.model, secrets=secret),
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
        preset = _provider(self.llm.provider_id)
        if preset.requires_api_key and not self.llm.api_key.strip():
            raise ValueError(f"{preset.label} 必须配置 API Key")
        if not self.llm.base_url.strip():
            raise ValueError("Base URL 不能为空")
        if not self.llm.model.strip():
            raise ValueError("模型名称不能为空")
        if not self.selected_files:
            raise ValueError("至少选择一份文档")
        if not 200 <= self.chunking.max_chars <= 20_000:
            raise ValueError("切片字符数必须在 200 到 20000 之间")

        folder = Path(self.document_folder)
        if not folder.exists() or not folder.is_dir():
            raise ValueError(f"文档目录不存在或不是文件夹：{folder}")

        for name in self.selected_files:
            if (
                not isinstance(name, str)
                or not name
                or name in {".", ".."}
                or "/" in name
                or "\\" in name
                or Path(name).name != name
            ):
                raise ValueError(f"选择项必须是当前目录的直接文件名：{name}")

            document = folder / name
            if not document.exists() or not document.is_file():
                raise ValueError(f"选择的文件不存在：{name}")
            if document.suffix.lower() not in {".md", ".txt"}:
                raise ValueError(f"只支持 .md 或 .txt 文件：{name}")

    def sanitized_snapshot(self) -> dict[str, object]:
        secret = (self.llm.api_key,) if self.llm.api_key else ()
        return {
            "run_name": redact_text(self.run_name, secrets=secret),
            "document_folder": redact_text(
                str(self.document_folder), secrets=secret
            ),
            "selected_files": list(self.selected_files),
            "llm": self.llm.sanitized(),
            "chunking": asdict(self.chunking),
            "retrieve_sentence_num": self.retrieve_sentence_num,
            "respect_legacy_breakpoint": self.respect_legacy_breakpoint,
            "reuse_entity_cache": self.reuse_entity_cache,
            "reuse_triplet_cache": self.reuse_triplet_cache,
        }

    @classmethod
    def from_settings(cls):
        from . import settings

        provider_id = os.environ.get("LLM_PROVIDER", "zhipu")
        return cls(
            run_name=settings.EXPERIMENT_RUN_NAME or "",
            document_folder=settings.DOCUMENT_FOLDER,
            selected_files=tuple(),
            llm=LLMConfig(
                provider_id=provider_id,
                api_key=resolve_provider_api_key(provider_id),
                base_url=os.environ.get(
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
