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


def _validate_graph_entity_payload(payload: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict) or set(payload) != {"entities"}:
        raise ValueError("图检索实体抽取输出不符合受控 JSON 契约")
    entities = payload["entities"]
    if not isinstance(entities, list) or len(entities) > 8:
        raise ValueError("图检索实体抽取输出不符合受控 JSON 契约")
    normalized: list[dict[str, Any]] = []
    for item in entities:
        if not isinstance(item, dict) or set(item) != {"name", "type", "evidence_block_ids"}:
            raise ValueError("图检索实体抽取输出不符合受控 JSON 契约")
        if not isinstance(item["name"], str) or not isinstance(item["type"], str):
            raise ValueError("图检索实体抽取输出不符合受控 JSON 契约")
        if not isinstance(item["evidence_block_ids"], list) or any(not isinstance(value, str) for value in item["evidence_block_ids"]):
            raise ValueError("图检索实体抽取输出不符合受控 JSON 契约")
        normalized.append(dict(item))
    return {"entities": normalized}


def _validate_reasonableness_payload(payload: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict) or set(payload) != {"issues"} or not isinstance(payload["issues"], list):
        raise ValueError("reasonable audit output violates the controlled JSON contract")
    normalized: list[dict[str, Any]] = []
    for item in payload["issues"]:
        if not isinstance(item, dict) or set(item) - {"summary", "suggestion", "evidence"}:
            raise ValueError("reasonable audit output violates the controlled JSON contract")
        summary = item.get("summary")
        evidence = item.get("evidence")
        if not isinstance(summary, str) or not summary.strip() or not isinstance(evidence, list) or any(not isinstance(value, str) for value in evidence):
            raise ValueError("reasonable audit output violates the controlled JSON contract")
        if "suggestion" in item and not isinstance(item["suggestion"], str):
            raise ValueError("reasonable audit output violates the controlled JSON contract")
        normalized.append(dict(item))
    return {"issues": normalized}


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
        if correction and task.route == "semantic_compliance":
            prompt["instruction"] += (
                "上一轮结论未通过结构或证据引用校验。现在只修正为 JSON：result_status 只能是 "
                "issue_found、no_issue 或 manual_review；每个问题必须有 category、summary、machine_status；"
                "issue_found 必须在顶层给出本输入中实际存在的 document_evidence_ids 和 normative_evidence_ids。"
            )
        if not legacy_package and task.route == "semantic_reasonableness":
            prompt["instruction"] = (
                "Return only a JSON object with one top-level field: issues. "
                "Each issue may contain only summary, suggestion, and evidence. "
                "summary and evidence are required; evidence is an array of IDs present in the supplied evidence. "
                "Example: {\"issues\":[{\"summary\":\"The construction sequence conflicts with a graph clue; manual review is required.\","
                "\"suggestion\":\"Verify and correct the construction sequence.\",\"evidence\":[\"block_id: B1\",\"graph_clue: A1\"]}]}. "
                "Do not use risk, description, or any other field, and do not claim normative non-compliance."
            )
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
        correction_content = None
        if not legacy_package and task.route == "semantic_reasonableness":
            try:
                result = _validate_reasonableness_payload(result)
            except (ValueError, TypeError):
                correction_messages = [
                    *messages,
                    {"role": "user", "content": (
                        "The prior output violates the JSON contract. Return only issues; every issue must use only "
                        "summary, suggestion, and evidence, with summary and evidence required. Do not use risk or description."
                    )},
                ]
                correction_response = client.chat.completions.create(
                    model=model, temperature=0, response_format={"type": "json_object"}, messages=correction_messages,
                )
                correction_content = correction_response.choices[0].message.content or "{}"
                try:
                    result = _validate_reasonableness_payload(json.loads(correction_content))
                except (ValueError, TypeError, json.JSONDecodeError):
                    # Preserve a legacy response for the runtime's explicit fallback mapper.
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
            "correction_raw_response": correction_content,
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
        returned_payload: dict[str, Any] = {}
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
                raw_payload = json.loads(content)
                parsed = _validate_retrieval_plan_payload(raw_payload)
                parsed_responses.append(parsed)
                returned_payload = parsed
                break
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                parsed_responses.append({"validation_error": str(exc)})
                try:
                    raw_payload = json.loads(content)
                except json.JSONDecodeError:
                    raw_payload = {}
                returned_payload = raw_payload if isinstance(raw_payload, dict) else {}
                parsed = {"validation_error": str(exc)}
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
        return returned_payload

    def graph_entity_extractor(task, evidence, schema_entity_types):
        prompt = {
            "task_id": task.task_id,
            "task_name": task.name,
            "schema_entity_types": list(schema_entity_types),
            "evidence": [dict(item) for item in evidence],
            "instruction": (
                "仅从给定方案证据原文抽取可用于图检索的短实体。名称必须在原文原样出现，"
                "类型必须来自 schema_entity_types；不得输出章节标题、完整句子、审核结论或推测。"
                "只返回 JSON 对象，顶层仅含 entities。entities 最多 8 项，每项必须且只能含"
                "name、type、evidence_block_ids。"
            ),
        }
        messages = [
            {"role": "system", "content": "受 Schema 约束的施工方案图检索实体抽取器，只输出 JSON。"},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        raw_responses: list[str] = []
        parsed_responses: list[Any] = []
        returned_payload: dict[str, Any] = {}
        for correction in (False, True):
            request_messages = messages if not correction else [
                *messages,
                {"role": "user", "content": "上一轮输出不符合受控 JSON 契约。仅返回 entities 数组，不要解释或其他字段。"},
            ]
            response = client.chat.completions.create(
                model=model, temperature=0, response_format={"type": "json_object"}, messages=request_messages,
            )
            content = response.choices[0].message.content or "{}"
            raw_responses.append(content)
            try:
                parsed = _validate_graph_entity_payload(json.loads(content))
                parsed_responses.append(parsed)
                returned_payload = parsed
                break
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                parsed_responses.append({"validation_error": str(exc)})
                if correction:
                    break
        graph_entity_extractor.last_interaction = {
            "kind": "graph_entity_extraction",
            "model": model,
            "prompt": prompt,
            "messages": messages,
            "raw_response": raw_responses[0] if raw_responses else None,
            "parsed_response": parsed_responses[0] if parsed_responses else None,
            "correction_raw_response": raw_responses[1] if len(raw_responses) > 1 else None,
            "correction_parsed_response": parsed_responses[1] if len(parsed_responses) > 1 else None,
        }
        return returned_payload

    call.retrieval_planner = retrieval_plan
    call.graph_entity_extractor = graph_entity_extractor

    return call
