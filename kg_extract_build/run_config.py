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
        default_base_url="https://api-inference.modelscope.cn/v1",
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


def _env_flag(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
    enable_thinking: bool = False
    temperature: float = 0.1

    def sanitized(self) -> dict[str, object]:
        secret = (self.api_key,) if self.api_key else ()
        return {
            "provider_id": self.provider_id,
            "base_url": redact_text(self.base_url, secrets=secret),
            "model": redact_text(self.model, secrets=secret),
            "api_key_configured": bool(self.api_key),
            "enable_thinking": self.enable_thinking,
            "temperature": self.temperature,
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
    document_source_type: str = "case"
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    retrieve_sentence_num: int = 10
    respect_legacy_breakpoint: bool = False
    reuse_entity_cache: bool = False
    reuse_triplet_cache: bool = False
    method_id: str = "R6"
    relation_strategy: str = "shared_context_batch"
    relation_batch_max_entities: int = 3
    relation_batch_min_overlap: float = 0.4
    relation_batch_max_context_chars: int = 8000

    def validate(self) -> None:
        from .method_profiles import get_method_profile
        from .source_profiles import SOURCE_TYPES

        profile = get_method_profile(self.method_id)
        preset = _provider(self.llm.provider_id)
        if preset.requires_api_key and not self.llm.api_key.strip():
            raise ValueError(f"{preset.label} 必须配置 API Key")
        if not self.llm.base_url.strip():
            raise ValueError("Base URL 不能为空")
        if not self.llm.model.strip():
            raise ValueError("模型名称不能为空")
        if not 0.0 <= self.llm.temperature <= 2.0:
            raise ValueError("温度必须在 0 到 2 之间")
        from .llm_thinking import is_thinking_only_model  # noqa: E402

        if (
            not self.llm.enable_thinking
            and is_thinking_only_model(
                self.llm.provider_id,
                self.llm.model,
            )
        ):
            raise ValueError(
                "当前模型属于仅思考模型，无法保证关闭思考；"
                "请更换模型或勾选'启用思考模式'"
            )
        if not self.selected_files:
            raise ValueError("至少选择一份文档")
        if self.document_source_type not in SOURCE_TYPES:
            raise ValueError("文档来源类型必须是 case、spec 或 auto")
        if not 200 <= self.chunking.max_chars <= 20_000:
            raise ValueError("切片字符数必须在 200 到 20000 之间")
        if self.relation_strategy not in {
            "llm_direct",
            "single_entity",
            "fixed_batch",
            "shared_context_batch",
        }:
            raise ValueError("关系抽取策略无效")
        if self.relation_strategy != profile.relation_strategy:
            raise ValueError("关系抽取策略必须由实验方法 Profile 固定")
        if not 1 <= self.relation_batch_max_entities <= 10:
            raise ValueError("关系批次实体数必须在 1 到 10 之间")
        if not 0.0 <= self.relation_batch_min_overlap <= 1.0:
            raise ValueError("共享上下文重叠阈值必须在 0 到 1 之间")
        if not 1000 <= self.relation_batch_max_context_chars <= 50_000:
            raise ValueError(
                "关系批次上下文字符数必须在 1000 到 50000 之间"
            )

        folder = Path(self.document_folder).expanduser().resolve()
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
            try:
                document.resolve().relative_to(folder)
            except ValueError as exc:
                raise ValueError(
                    f"选择的文件不在文档目录内：{name}"
                ) from exc
            if document.suffix.lower() not in {".md", ".txt"}:
                raise ValueError(f"只支持 .md 或 .txt 文件：{name}")

    def sanitized_snapshot(self) -> dict[str, object]:
        from .method_profiles import get_method_profile

        profile = get_method_profile(self.method_id)
        secret = (self.llm.api_key,) if self.llm.api_key else ()
        return {
            "run_name": redact_text(self.run_name, secrets=secret),
            "document_folder": redact_text(
                str(self.document_folder), secrets=secret
            ),
            "selected_files": [
                redact_text(name, secrets=secret)
                for name in self.selected_files
            ],
            "document_source_type_requested": self.document_source_type,
            "llm": self.llm.sanitized(),
            "chunking": asdict(self.chunking),
            "retrieve_sentence_num": self.retrieve_sentence_num,
            "respect_legacy_breakpoint": self.respect_legacy_breakpoint,
            "reuse_entity_cache": self.reuse_entity_cache,
            "reuse_triplet_cache": self.reuse_triplet_cache,
            "method_id": profile.method_id,
            "prompt_version": profile.prompt_version,
            "enable_schema_validation": profile.enable_schema_validation,
            "method": profile.snapshot(),
            "relation_batch": {
                "strategy": self.relation_strategy,
                "max_entities": self.relation_batch_max_entities,
                "min_overlap": self.relation_batch_min_overlap,
                "max_context_chars": (
                    self.relation_batch_max_context_chars
                ),
            },
        }

    @classmethod
    def from_settings(cls):
        from . import settings
        from .method_profiles import get_method_profile

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
                enable_thinking=_env_flag(
                    os.environ.get("LLM_ENABLE_THINKING", "")
                ),
            ),
            document_source_type=os.environ.get(
                "KG_DOCUMENT_SOURCE_TYPE", "auto"
            ),
            chunking=ChunkingConfig(),
            retrieve_sentence_num=settings.RETRIEVE_SENTENCE_NUM,
            respect_legacy_breakpoint=settings.RESPECT_LEGACY_BREAKPOINT,
            reuse_entity_cache=settings.REUSE_ENTITY_CACHE,
            reuse_triplet_cache=settings.REUSE_TRIPLET_CACHE,
            method_id=os.environ.get("KG_METHOD_ID", "R6"),
            relation_strategy=os.environ.get(
                "KG_RELATION_STRATEGY",
                get_method_profile(os.environ.get("KG_METHOD_ID", "R6")).relation_strategy,
            ),
            relation_batch_max_entities=int(
                os.environ.get(
                    "KG_RELATION_BATCH_MAX_ENTITIES",
                    "3",
                )
            ),
            relation_batch_min_overlap=float(
                os.environ.get(
                    "KG_RELATION_BATCH_MIN_OVERLAP",
                    "0.4",
                )
            ),
            relation_batch_max_context_chars=int(
                os.environ.get(
                    "KG_RELATION_BATCH_MAX_CONTEXT_CHARS",
                    "8000",
                )
            ),
        )
