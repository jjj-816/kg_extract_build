"""OpenAI-compatible provider adapter for semantic audit tasks.

The adapter is deliberately narrow: it returns structured JSON to the existing
``SemanticRuntime`` validation boundary and never exposes the API key in a
report or diagnostic.
"""

from __future__ import annotations

import json
from typing import Any, Callable


def build_structured_model(*, api_key: str, base_url: str, model: str, client_factory: Callable[..., Any] | None = None):
    """Build the callable expected by :class:`SemanticRuntime`.

    Client construction is deferred until this function is called so an
    unavailable provider fails the affected task and does not prevent page
    rendering or deterministic tasks from completing.
    """
    if not api_key and "localhost" not in base_url and "127.0.0.1" not in base_url:
        raise ValueError("审核 provider 未配置 API Key")
    if not base_url.strip() or not model.strip():
        raise ValueError("审核 provider 缺少 Base URL 或模型名称")

    factory = client_factory
    if factory is None:
        from openai import OpenAI

        factory = OpenAI
    client = factory(api_key=api_key or "ollama", base_url=base_url, timeout=120.0)

    def call(task, package, *, correction=False):
        prompt = {
            "task_id": task.task_id,
            "task_name": task.name,
            "route": task.route,
            "correction_pass": correction,
            "evidence_package_id": package.package_id,
            "evidence": [dict(item) for item in package.evidence],
            "instruction": "仅依据给定证据返回 JSON；不得补造规范或证据。",
        }
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "你是审计语义审核器，必须输出符合约定的 JSON。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content or "{}"
        result = json.loads(content)
        result.setdefault("package_id", package.package_id)
        return result

    return call
