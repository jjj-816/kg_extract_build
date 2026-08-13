"""OpenAI-compatible provider adapter for semantic audit tasks.

The adapter is deliberately narrow: it returns structured JSON to the existing
``SemanticRuntime`` validation boundary and never exposes the API key in a
report or diagnostic.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .semantic_runtime import EvidencePackage


_RETRIEVAL_PLAN_FIELDS = (
    "document_block_ids",
    "normative_queries",
    "graph_queries",
    "relationship_types",
)


def _validate_retrieval_plan_payload(payload: Any) -> dict[str, list[str]]:
    """Accept only the executable retrieval-planning contract from a provider."""
    if not isinstance(payload, dict) or set(payload) != set(_RETRIEVAL_PLAN_FIELDS):
        raise ValueError("检索规划输出不符合受控 JSON 契约")
    validated: dict[str, list[str]] = {}
    for field in _RETRIEVAL_PLAN_FIELDS:
        values = payload[field]
        if not isinstance(values, list) or len(values) > 5 or any(not isinstance(value, str) for value in values):
            raise ValueError("检索规划输出不符合受控 JSON 契约")
        validated[field] = values
    return validated


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

    def call(task, package_or_evidence, graph_result=None, *, correction=False, run_id=None):
        """Adapt every semantic execution route to the selected provider.

        ``SemanticRuntime`` uses :class:`EvidencePackage`, while the production
        compliance and reasonableness executors pass their route-specific
        evidence contracts.  Keep those contracts distinct instead of forcing
        the production routes through the legacy package-id validator.
        """
        legacy_package = isinstance(package_or_evidence, EvidencePackage)
        if legacy_package:
            evidence = [dict(item) for item in package_or_evidence.evidence]
            route_contract = {
                "evidence_package_id": package_or_evidence.package_id,
                "evidence": evidence,
                "instruction": (
                    "仅依据给定证据返回最终审核 JSON，不要回显请求内容或 instruction。"
                    "顶层必须包含 result_status（取值 no_issue、issue_found、manual_review）、"
                    "issues（数组）和 package_id（必须等于 evidence_package_id）。"
                    "不得补造规范或证据。"
                ),
            }
        elif isinstance(package_or_evidence, dict) and task.route == "semantic_compliance":
            route_contract = {
                "run_id": package_or_evidence.get("run_id"),
                "document_evidence": [dict(item) for item in package_or_evidence.get("document_evidence", ())],
                "normative_evidence": [dict(item) for item in package_or_evidence.get("normative_evidence", ())],
                "instruction": (
                    "仅依据方案证据和规范条款返回合规审核 JSON。顶层必须包含 result_status、issues、"
                    "document_evidence_ids 和 normative_evidence_ids；不符合时必须同时引用两类证据。"
                    "不得补造规范或证据。"
                ),
            }
        else:
            route_contract = {
                "run_id": run_id,
                "document_evidence": [dict(item) for item in package_or_evidence],
                "graph_clues": [
                    {
                        "clue_id": clue.clue_id,
                        "assertion_id": clue.assertion_id,
                        "source_document_id": clue.source_document_id,
                        "evidence_sentence": clue.evidence_sentence,
                        "summary": clue.summary,
                    }
                    for clue in getattr(graph_result, "clues", ())
                ],
                "instruction": (
                    "仅依据方案证据和图检索线索返回合理性审核 JSON。顶层必须包含 issues 数组；"
                    "每项仅作为需人工复核的工程风险提示，不得声称规范不符合。"
                ),
            }
        prompt = {
            "task_id": task.task_id,
            "task_name": task.name,
            "route": task.route,
            "correction_pass": correction,
            **route_contract,
        }
        messages = [
            {"role": "system", "content": "审计语义审核器，只输出最终 JSON。"},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        messages = [
            {"role": "system", "content": "????????????? JSON?"},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        response = client.chat.completions.create(
            model=model, temperature=0, response_format={"type": "json_object"}, messages=messages,
        )
        content = response.choices[0].message.content or "{}"
        result = json.loads(content)
        if legacy_package:
            result.setdefault("package_id", package_or_evidence.package_id)
        call.last_interaction = {
            "kind": "audit_conclusion",
            "model": model,
            "prompt": prompt,
            "messages": messages,
            "raw_response": content,
            "parsed_response": result,
        }
        return result

    def retrieval_plan(task, evidence, *, mode="retrieval_planning", instruction=""):
        prompt = {
            "task_id": task.task_id,
            "task_name": task.name,
            "mode": mode,
            "evidence": [dict(item) for item in evidence],
            "instruction": instruction or (
                "只返回 JSON 对象，且顶层只能包含 document_block_ids、normative_queries、"
                "graph_queries、relationship_types 四个字段。每个字段必须是最多 5 个字符串的数组；"
                "查询词必须依据给定方案证据，不得返回审核结论或证据 ID。"
            ),
        }
        messages = [
            {"role": "system", "content": "受证据约束的检索规划器，只输出 JSON。"},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        raw_responses: list[str] = []
        parsed_responses: list[Any] = []
        for correction in (False, True):
            request_messages = messages
            if correction:
                request_messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "上一轮输出不符合受控 JSON 契约。仅返回要求的四个顶层数组字段，"
                            "不要解释或添加其他字段。"
                        ),
                    },
                ]
            response = client.chat.completions.create(
                model=model, temperature=0, response_format={"type": "json_object"}, messages=request_messages,
            )
            content = response.choices[0].message.content or "{}"
            raw_responses.append(content)
            try:
                parsed = _validate_retrieval_plan_payload(json.loads(content))
                parsed_responses.append(parsed)
                break
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                parsed_responses.append({"validation_error": str(exc)})
                parsed = {}
                if correction:
                    break
        retrieval_plan.last_interaction = {
            "kind": "retrieval_planning",
            "model": model,
            "prompt": prompt,
            "messages": messages,
            "raw_response": raw_responses[0],
            "parsed_response": parsed,
            "correction_raw_response": raw_responses[1] if len(raw_responses) > 1 else None,
            "correction_parsed_response": parsed_responses[1] if len(parsed_responses) > 1 else None,
        }
        return parsed

    call.retrieval_planner = retrieval_plan

    return call
