import json
import re
import time

from openai import OpenAI

from .llm_thinking import build_thinking_options
from .preprocess import is_valid_entity_candidate
from .run_config import redact_text
from .settings import UNKNOWN_TYPE


class TripletGenerator:
    def __init__(
        self,
        api_key,
        base_url,
        model_name,
        doc_name,
        debug_dir,
        schema,
        known_entities=None,
        recorder=None,
        provider_id="custom",
        enable_thinking=False,
        temperature=0.1,
        prompt_version="relation-batch-v1",
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
        self.model = model_name
        self.schema = schema
        self.known_entities = known_entities or {}
        self.recorder = recorder
        self.debug_dir = debug_dir / self._clean_filename(doc_name.rsplit(".", 1)[0])
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self._secret_values = (api_key,)
        self._thinking_options = build_thinking_options(
            provider_id,
            enable_thinking,
        )
        self.temperature = float(temperature)
        self.prompt_version = str(prompt_version)
        self.type_completion_call_count = 0

    def generate(self, entity, evidence):
        entity_name = entity["name"]
        entity_type = entity.get("type", UNKNOWN_TYPE)
        evidence_by_id = {
            int(item["sentence_index"]): str(item["sentence"])
            for item in evidence
        }
        prompt = self._build_prompt(entity_name, entity_type, evidence_by_id)
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                **self._thinking_options,
            )
            raw_result = response.choices[0].message.content.strip()
            triplets = self._parse_triplets(
                raw_result, entity_name, entity_type,
                "\n".join(evidence_by_id.values()), set(evidence_by_id), evidence_by_id,
            )
            llm_call_id = None
            if self.recorder is not None:
                llm_call_id = self.recorder.record_llm_call(
                    stage="triplet_extraction",
                    prompt=prompt,
                    raw_response=raw_result,
                    parsed=triplets,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    entity_name=entity_name,
                    metadata={"evidence_ids": sorted(evidence_by_id), "entity_type": entity_type, "prompt_version": self.prompt_version},
                )
                self.recorder.record_triplets(
                    "raw",
                    triplets,
                    entity_name=entity_name,
                    source_kind="model",
                    source_llm_call_id=llm_call_id,
                )
            self._save_debug(
                entity_name,
                prompt,
                raw_result,
                triplets,
                llm_call_id=llm_call_id,
            )
            return triplets
        except Exception as exc:
            safe_error = redact_text(str(exc), secrets=self._secret_values)
            print(f"三元组抽取失败 {entity_name}：{safe_error}")
            if self.recorder is not None:
                self.recorder.record_llm_call(
                    stage="triplet_extraction",
                    prompt=prompt,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    success=False,
                    error_message=safe_error,
                    entity_name=entity_name,
                    metadata={"evidence_ids": sorted(evidence_by_id), "entity_type": entity_type, "prompt_version": self.prompt_version},
                )
            return []

    def generate_batch(
        self,
        entities,
        evidence,
        entity_evidence_ids,
        batch_metadata=None,
    ):
        prompt = self._build_batch_prompt(
            entities,
            evidence,
            entity_evidence_ids,
        )
        started = time.perf_counter()
        raw_result = None
        entity_names = [entity["name"] for entity in entities]
        metadata = {
            "strategy": "shared_context_batch",
            "prompt_version": self.prompt_version,
            "batch_entities": entity_names,
            "entity_evidence_ids": {
                name: list(ids)
                for name, ids in entity_evidence_ids.items()
            },
            **dict(batch_metadata or {}),
        }
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                **self._thinking_options,
            )
            raw_result = response.choices[0].message.content.strip()
            raw_items = self._parse_batch_array(raw_result)
            evidence_by_id = {
                int(item["sentence_index"]): str(item["sentence"])
                for item in evidence
            }
            results = {}
            for entity in entities:
                entity_name = entity["name"]
                entity_type = entity.get("type", UNKNOWN_TYPE)
                context = "\n".join(
                    evidence_by_id[index]
                    for index in entity_evidence_ids[entity_name]
                    if index in evidence_by_id
                )
                results[entity_name] = self._parse_triplets(
                    json.dumps(raw_items, ensure_ascii=False),
                    entity_name,
                    entity_type,
                    context,
                    set(entity_evidence_ids[entity_name]),
                    evidence_by_id,
                )

            llm_call_id = None
            if self.recorder is not None:
                llm_call_id = self.recorder.record_llm_call(
                    stage="triplet_extraction_batch",
                    prompt=prompt,
                    raw_response=raw_result,
                    parsed=results,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    metadata=metadata,
                )
                for entity_name, triplets in results.items():
                    self.recorder.record_triplets(
                        "raw",
                        triplets,
                        entity_name=entity_name,
                        source_kind="model_batch",
                        source_llm_call_id=llm_call_id,
                    )

            for entity_name, triplets in results.items():
                self._save_debug(
                    entity_name,
                    prompt,
                    raw_result,
                    triplets,
                    llm_call_id=llm_call_id,
                    metadata=metadata,
                )
            return results
        except Exception as exc:
            safe_error = redact_text(
                str(exc),
                secrets=self._secret_values,
            )
            print(f"批量三元组抽取失败：{safe_error}")
            if self.recorder is not None:
                self.recorder.record_llm_call(
                    stage="triplet_extraction_batch",
                    prompt=prompt,
                    raw_response=raw_result,
                    latency_ms=int(
                        (time.perf_counter() - started) * 1000
                    ),
                    success=False,
                    error_message=safe_error,
                    metadata=metadata,
                )
            raise RuntimeError(
                f"批量三元组抽取失败：{safe_error}"
            ) from exc

    def generate_direct(self, document_text):
        """Extract document-level triples for the R2 LLM-Direct baseline."""
        prompt = self._build_direct_prompt(document_text)
        started = time.perf_counter()
        raw_result = None
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                **self._thinking_options,
            )
            raw_result = response.choices[0].message.content.strip()
            triplets = self._parse_direct_triplets(raw_result)
            llm_call_id = None
            if self.recorder is not None:
                llm_call_id = self.recorder.record_llm_call(
                    stage="triplet_extraction_direct",
                    prompt=prompt,
                    raw_response=raw_result,
                    parsed=triplets,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    metadata={"strategy": "llm_direct", "prompt_version": self.prompt_version},
                )
                self.recorder.record_triplets(
                    "raw", triplets, entity_name="__document__",
                    source_kind="model_direct", source_llm_call_id=llm_call_id,
                )
            self._save_debug("__document__", prompt, raw_result, triplets, llm_call_id=llm_call_id)
            return triplets
        except Exception as exc:
            safe_error = redact_text(str(exc), secrets=self._secret_values)
            if self.recorder is not None:
                self.recorder.record_llm_call(
                    stage="triplet_extraction_direct", prompt=prompt,
                    raw_response=raw_result,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    success=False, error_message=safe_error,
                    metadata={"strategy": "llm_direct", "prompt_version": self.prompt_version},
                )
            raise RuntimeError(f"直接三元组抽取失败：{safe_error}") from exc

    def _build_batch_prompt(
        self,
        entities,
        evidence,
        entity_evidence_ids,
    ):
        evidence_lines = [
            f"[S{int(item['sentence_index'])}] {item['sentence']}"
            for item in evidence
        ]
        target_blocks = []
        for entity in entities:
            entity_name = entity["name"]
            entity_type = entity.get("type", UNKNOWN_TYPE)
            evidence_labels = ", ".join(
                f"S{index}"
                for index in entity_evidence_ids[entity_name]
            )
            target_blocks.append(
                "\n".join(
                    [
                        f"- head={entity_name}",
                        f"  head_type={entity_type}",
                        f"  evidence={evidence_labels}",
                        "  allowed_relations:",
                        self.schema.render_allowed_relation_schema(
                            entity_type
                        ),
                        "  allowed_tail_types: "
                        + self.schema.render_allowed_tail_types(
                            entity_type
                        ),
                        "  required_output_field: evidence_sentence_ids, for example [1]",
                    ]
                )
            )
        return f"""任务：基于指定证据，为多个目标实体抽取知识图谱三元组。

【证据句】
{chr(10).join(evidence_lines)}

【目标实体】
{chr(10).join(target_blocks)}

Required JSON output format:
[
  {{"head":"target head","head_type":"type","relation":"relation","tail":"tail","tail_type":"type","evidence_sentence_ids":[1]}}
]

约束：
- head 必须是目标实体之一，禁止输出其他 head。
- 每个 head 只能使用其 evidence 列出的证据句。
- relation 和 tail_type 必须符合该 head 的允许范围。
- tail 必须在该 head 的证据原文中出现，不能推断或改写。
- 只输出一个 JSON 数组；没有关系的实体不需要输出记录。

格式：
[
  {{"head": "目标实体", "head_type": "实体类型", "relation": "关系", "tail": "尾实体", "tail_type": "尾实体类型"}}
]

Each (head, relation, tail) may appear at most once. Never repeat an item.
At most 5 triplets per head. If no new valid item remains, end the JSON array immediately.

Final output schema (use this exact six-field structure):
[
  {{"head":"target head","head_type":"type","relation":"relation","tail":"tail","tail_type":"type","evidence_sentence_ids":[142]}}
]
evidence_sentence_ids is mandatory and must be an integer array such as [142], never [S142].
"""

    def _build_direct_prompt(self, document_text):
        return f"""任务：直接从下列施工文档抽取知识图谱三元组。

实体类型：
{self.schema.render_entity_schema()}

关系类型：
{self.schema.render_relation_schema()}

仅输出 JSON 数组，不要解释。每项必须恰好包含 head、head_type、relation、tail、tail_type。
head 和 tail 必须是文档中实际出现的短实体；不要输出完整句子；不要重复三元组。

格式：
[
  {{"head":"实体","head_type":"实体类型","relation":"关系","tail":"实体","tail_type":"实体类型"}}
]

文档：
{document_text}
"""

    def _parse_direct_triplets(self, raw_text):
        items = self._parse_batch_array(raw_text)
        triplets = []
        seen = set()
        for item in items:
            head = str(item.get("head", "")).strip()
            tail = str(item.get("tail", "")).strip()
            relation = self.schema.normalize_relation(str(item.get("relation", "")).strip())
            head_type = self.schema.normalize_entity_type(str(item.get("head_type", "")).strip())
            tail_type = self.schema.normalize_entity_type(str(item.get("tail_type", "")).strip())
            if not head or not tail or not relation:
                continue
            if not is_valid_entity_candidate(head) or not is_valid_entity_candidate(tail):
                continue
            key = (head, head_type, relation, tail, tail_type)
            if key in seen:
                continue
            seen.add(key)
            triplets.append({
                "head": head, "head_type": head_type, "relation": relation,
                "tail": tail, "tail_type": tail_type,
            })
        return triplets

    def _parse_batch_array(self, raw_text):
        raw_text = self._normalize_evidence_id_syntax(raw_text)
        match = re.search(r"\[[\s\S]*\]", raw_text)
        payload = match.group(0) if match else raw_text
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = self._recover_complete_batch_items(payload)
        if not isinstance(data, list):
            raise ValueError("批量三元组响应必须是 JSON 数组")
        return self._deduplicate_batch_items(data)

    @staticmethod
    def _recover_complete_batch_items(payload):
        decoder = json.JSONDecoder()
        items = []
        index = payload.find("[") + 1
        length = len(payload)
        while index < length:
            while index < length and payload[index].isspace():
                index += 1
            if index >= length or payload[index] == "]":
                break
            if payload[index] == ",":
                index += 1
                continue
            try:
                item, index = decoder.raw_decode(payload, index)
            except json.JSONDecodeError:
                if items:
                    break
                raise
            if isinstance(item, dict):
                items.append(item)
        if not items:
            raise ValueError("批量三元组响应不包含可恢复的完整对象")
        return items

    @staticmethod
    def _deduplicate_batch_items(items):
        unique_items = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            unique_items.append(item)
        return unique_items

    @staticmethod
    def _normalize_evidence_id_syntax(raw_text):
        return re.sub(
            r"(?<=[\[,])\s*S(\d+)(?=\s*[,\]])",
            r"\1",
            raw_text,
        )

    def load_saved_triplets(self, entity_name):
        save_path = self._debug_path(entity_name)
        if not save_path.exists():
            return None
        try:
            with save_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            print(f"已存三元组文件读取失败，将重新抽取 {entity_name}：{exc}")
            return None

        triplets = payload.get("triplets")
        if not isinstance(triplets, list):
            print(f"已存三元组文件格式异常，将重新抽取 {entity_name}")
            return None
        return triplets

    def _build_prompt(self, entity_name, entity_type, evidence_by_id):
        allowed_relations = self.schema.render_allowed_relation_schema(entity_type)
        allowed_tail_types = self.schema.render_allowed_tail_types(entity_type)
        return f"""任务：从上下文抽取以指定 head 为中心的知识图谱三元组。

head="{entity_name}"
head_type="{entity_type}"

允许关系（relation -> tail_type）：
{allowed_relations}

可选 tail_type：
{allowed_tail_types}

- Every output item must include evidence_sentence_ids, a non-empty list of S-number integers that directly contain its tail.

Required JSON item example:
{{"head":"{entity_name}","head_type":"{entity_type}","relation":"relation","tail":"tail","tail_type":"type","evidence_sentence_ids":[1]}}

约束：
- head 和 head_type 必须固定为上面的值。
- relation 只能从允许关系列表中选择；若无匹配关系，输出 []。
- tail 必须是上下文中原文出现的短实体、编号、参数或风险项，不能是完整句子。
- tail_type 只能从可选 tail_type 中选择；无法判断时填 "{UNKNOWN_TYPE}"。
- 只输出 JSON 数组，不要解释。

格式：
[
  {{"head": "{entity_name}", "head_type": "{entity_type}", "relation": "关系类型", "tail": "尾实体", "tail_type": "实体类型"}}
]

上下文：
{chr(10).join(f'[S{index}] {sentence}' for index, sentence in evidence_by_id.items())}
"""

    def _parse_triplets(
        self, raw_text, entity_name, entity_type, context,
        allowed_evidence_ids=None, evidence_by_id=None,
    ):
        if not hasattr(self, "type_completion_call_count"):
            self.type_completion_call_count = 0
        raw_text = self._normalize_evidence_id_syntax(raw_text)
        try:
            match = re.search(r"\[[\s\S]*\]", raw_text)
            payload = match.group(0) if match else raw_text
            data = json.loads(payload)
        except Exception:
            data = self._parse_line_triplets(raw_text, entity_type)

        valid_triplets = []
        for item in data:
            if not isinstance(item, dict):
                continue
            head = str(item.get("head", "")).strip()
            relation = self.schema.normalize_relation(str(item.get("relation", "")).strip())
            tail = str(item.get("tail", "")).strip()
            head_type = self.schema.normalize_entity_type(entity_type)
            tail_type = self.schema.normalize_entity_type(str(item.get("tail_type", "")).strip())

            if head in self.known_entities:
                head = self.known_entities[head].get("name", head)

            if not is_valid_entity_candidate(head):
                continue
            if head != entity_name or not relation or not tail:
                continue
            if len(tail) > 30:
                continue
            evidence_ids = item.get("evidence_sentence_ids", [])
            if allowed_evidence_ids is not None:
                if not isinstance(evidence_ids, list) or not evidence_ids:
                    continue
                try:
                    evidence_ids = [int(value) for value in evidence_ids]
                except (TypeError, ValueError):
                    continue
                if not set(evidence_ids).issubset(allowed_evidence_ids):
                    continue
                selected_text = "\n".join(
                    evidence_by_id[index]
                    for index in evidence_ids
                    if index in evidence_by_id
                )
                if tail not in selected_text:
                    continue
            if tail not in context and tail not in self.known_entities:
                continue
            if tail in self.known_entities and tail_type == UNKNOWN_TYPE:
                tail_type = self.schema.normalize_entity_type(
                    self.known_entities[tail].get("type", UNKNOWN_TYPE)
                )

            candidate = {
                "head": head,
                "head_type": head_type,
                "relation": relation,
                "tail": tail,
                "tail_type": tail_type,
                "evidence_sentence_ids": evidence_ids,
            }
            if allowed_evidence_ids is None:
                candidate.pop("evidence_sentence_ids")
            if (
                not self._is_final_entity_type_allowed(head_type)
                or not self._is_final_entity_type_allowed(tail_type)
            ):
                candidate = self.complete_unknown_types(candidate, context)
                if candidate is None:
                    continue
                head_type = candidate["head_type"]
                tail_type = candidate["tail_type"]

            if (
                not self._is_final_entity_type_allowed(head_type)
                or not self._is_final_entity_type_allowed(tail_type)
            ):
                continue

            if self.schema.is_relation_allowed(relation, head_type, tail_type):
                valid_triplets.append({
                    "head": head,
                    "head_type": head_type,
                    "relation": relation,
                    "tail": tail,
                    "tail_type": tail_type,
                    **({"evidence_sentence_ids": evidence_ids} if allowed_evidence_ids is not None else {}),
                })
                continue

            if self.schema.is_relation_allowed(relation, tail_type, head_type):
                valid_triplets.append({
                    "head": tail,
                    "head_type": tail_type,
                    "relation": relation,
                    "tail": head,
                    "tail_type": head_type,
                    **({"evidence_sentence_ids": evidence_ids} if allowed_evidence_ids is not None else {}),
                })
        return valid_triplets

    def _is_final_entity_type_allowed(self, entity_type):
        validator = getattr(self.schema, "is_final_entity_type_allowed", None)
        if validator is not None:
            return validator(entity_type)
        return bool(entity_type) and entity_type != UNKNOWN_TYPE

    def complete_unknown_types(self, triplet, context):
        prompt = self._build_type_completion_prompt(triplet, context)
        started = time.perf_counter()
        raw_result = None
        parsed = None
        error_message = None
        try:
            self.type_completion_call_count = (
                getattr(self, "type_completion_call_count", 0) + 1
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                **self._thinking_options,
            )
            raw_result = response.choices[0].message.content.strip()
            result = json.loads(raw_result)
            if not isinstance(result, dict) or set(result) != {
                "head_type", "tail_type",
            }:
                raise ValueError("type completion must be a JSON object with head_type and tail_type")
            head_type = self.schema.normalize_entity_type(result["head_type"])
            tail_type = self.schema.normalize_entity_type(result["tail_type"])
            parsed = {"head_type": head_type, "tail_type": tail_type}
            if (
                not self._is_final_entity_type_allowed(head_type)
                or not self._is_final_entity_type_allowed(tail_type)
            ):
                raise ValueError("type completion returned an unknown or invalid entity type")
            if not self.schema.is_relation_allowed(
                triplet["relation"], head_type, tail_type
            ):
                raise ValueError("type completion violates the relation schema")
            return {
                **triplet,
                "head_type": head_type,
                "tail_type": tail_type,
            }
        except Exception as exc:
            error_message = redact_text(str(exc), secrets=self._secret_values)
            return None
        finally:
            if self.recorder is not None:
                self.recorder.record_llm_call(
                    stage="triplet_type_completion",
                    prompt=prompt,
                    raw_response=raw_result,
                    parsed=parsed,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    success=error_message is None,
                    error_message=error_message,
                    entity_name=triplet["head"],
                    metadata={
                        "context": context,
                        "triplet": dict(triplet),
                    },
                )

    def _build_type_completion_prompt(self, triplet, context):
        return f'''Task: assign final schema entity types to this existing triplet.

Keep head, relation, and tail exactly unchanged. Do not create, rename, split, or merge entities.
Use the evidence only to choose types. Return one JSON object and nothing else, exactly:
{{"head_type":"Schema entity type","tail_type":"Schema entity type"}}

head={triplet["head"]}
relation={triplet["relation"]}
tail={triplet["tail"]}
current_head_type={triplet["head_type"]}
current_tail_type={triplet["tail_type"]}

Schema entity types:
{self.schema.render_entity_schema()}

Evidence:
{context}
'''

    def _parse_line_triplets(self, raw_text, entity_type):
        triplets = []
        for line in raw_text.splitlines():
            line = line.strip()
            if not line or " - " not in line:
                continue
            parts = [p.strip() for p in line.split(" - ")]
            if len(parts) == 3:
                triplets.append({
                    "head": parts[0],
                    "head_type": entity_type,
                    "relation": parts[1],
                    "tail": parts[2],
                    "tail_type": self.known_entities.get(parts[2], {}).get("type", UNKNOWN_TYPE),
                })
        return triplets

    def _save_debug(
        self,
        entity_name,
        prompt,
        raw_text,
        triplets,
        llm_call_id=None,
        metadata=None,
    ):
        save_path = self._debug_path(entity_name)
        with save_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "entity": entity_name,
                    "prompt": prompt,
                    "raw": raw_text,
                    "triplets": triplets,
                    "llm_call_id": llm_call_id,
                    "metadata": metadata or {},
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    def _debug_path(self, entity_name):
        return self.debug_dir / f"{self._clean_filename(entity_name)}.json"

    def _clean_filename(self, text):
        for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
            text = text.replace(char, "_")
        return text.strip()


class TripletCorrector:
    def __init__(self, schema):
        self.schema = schema

    def correct(self, raw_triplet_map):
        valid_triplets = []
        for entity_name, triplets in raw_triplet_map.items():
            for triplet in triplets:
                head = triplet.get("head", "").strip()
                head_type = self.schema.normalize_entity_type(
                    triplet.get("head_type", UNKNOWN_TYPE).strip()
                )
                relation = triplet.get("relation", "").strip()
                tail = triplet.get("tail", "").strip()
                tail_type = self.schema.normalize_entity_type(
                    triplet.get("tail_type", UNKNOWN_TYPE).strip()
                )
                if (
                    is_valid_entity_candidate(head)
                    and (head == entity_name or tail == entity_name)
                    and self._is_final_entity_type_allowed(head_type)
                    and self._is_final_entity_type_allowed(tail_type)
                    and self.schema.is_relation_allowed(relation, head_type, tail_type)
                ):
                    valid_triplets.append({
                        "head": head,
                        "head_type": head_type,
                        "relation": relation,
                        "tail": tail,
                        "tail_type": tail_type,
                        "evidence_sentence_ids": triplet.get("evidence_sentence_ids", []),
                    })
        deduplicated = {}
        for triplet in valid_triplets:
            key = (
                triplet["head"], triplet["head_type"], triplet["relation"],
                triplet["tail"], triplet["tail_type"],
            )
            deduplicated.setdefault(key, triplet)
        return list(deduplicated.values())

    def _is_final_entity_type_allowed(self, entity_type):
        validator = getattr(self.schema, "is_final_entity_type_allowed", None)
        if validator is not None:
            return validator(entity_type)
        return bool(entity_type) and entity_type != UNKNOWN_TYPE
