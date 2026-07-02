import json
import re
import time

from openai import OpenAI

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
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model_name
        self.schema = schema
        self.known_entities = known_entities or {}
        self.recorder = recorder
        self.debug_dir = debug_dir / self._clean_filename(doc_name.rsplit(".", 1)[0])
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self._secret_values = (api_key,)

    def generate(self, entity, context):
        entity_name = entity["name"]
        entity_type = entity.get("type", UNKNOWN_TYPE)
        prompt = self._build_prompt(entity_name, entity_type, context)
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                extra_body={"thinking": {"type": "disabled"}},
            )
            raw_result = response.choices[0].message.content.strip()
            triplets = self._parse_triplets(raw_result, entity_name, entity_type, context)
            llm_call_id = None
            if self.recorder is not None:
                llm_call_id = self.recorder.record_llm_call(
                    stage="triplet_extraction",
                    prompt=prompt,
                    raw_response=raw_result,
                    parsed=triplets,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    entity_name=entity_name,
                    metadata={"context": context, "entity_type": entity_type},
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
                    metadata={"context": context, "entity_type": entity_type},
                )
            return []

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

    def _build_prompt(self, entity_name, entity_type, context):
        allowed_relations = self.schema.render_allowed_relation_schema(entity_type)
        allowed_tail_types = self.schema.render_allowed_tail_types(entity_type)
        return f"""任务：从上下文抽取以指定 head 为中心的知识图谱三元组。

head="{entity_name}"
head_type="{entity_type}"

允许关系（relation -> tail_type）：
{allowed_relations}

可选 tail_type：
{allowed_tail_types}

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
{context}
"""

    def _parse_triplets(self, raw_text, entity_name, entity_type, context):
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
            tail_type = self.schema.normalize_entity_type(str(item.get("tail_type", "")).strip())

            if head in self.known_entities:
                head = self.known_entities[head].get("name", head)

            if head != entity_name or not relation or not tail:
                continue
            if len(tail) > 30:
                continue
            if tail not in context and tail not in self.known_entities:
                continue
            if tail in self.known_entities and tail_type == UNKNOWN_TYPE:
                tail_type = self.known_entities[tail].get("type", UNKNOWN_TYPE)
            if self.schema.is_relation_allowed(relation, entity_type, tail_type):
                valid_triplets.append({
                    "head": head,
                    "head_type": entity_type,
                    "relation": relation,
                    "tail": tail,
                    "tail_type": tail_type,
                })
                continue

            if self.schema.is_relation_allowed(relation, tail_type, entity_type):
                valid_triplets.append({
                    "head": tail,
                    "head_type": tail_type,
                    "relation": relation,
                    "tail": head,
                    "tail_type": entity_type,
                })
        return valid_triplets

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
                head_type = triplet.get("head_type", UNKNOWN_TYPE).strip()
                relation = triplet.get("relation", "").strip()
                tail = triplet.get("tail", "").strip()
                tail_type = triplet.get("tail_type", UNKNOWN_TYPE).strip()
                if (
                    (head == entity_name or tail == entity_name)
                    and self.schema.is_relation_allowed(relation, head_type, tail_type)
                ):
                    valid_triplets.append((head, head_type, relation, tail, tail_type))
        return list(set(valid_triplets))
