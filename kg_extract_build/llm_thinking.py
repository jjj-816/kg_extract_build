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
