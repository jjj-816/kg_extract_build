import json
import re
import time

from openai import OpenAI

from .run_config import redact_text
from .settings import UNKNOWN_TYPE


NORMATIVE_ENTITY_TYPE = "规范条款"


class LongDocLLMEntityExtractor:
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
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
        self.model = model_name
        self.schema = schema
        self.max_chunk_size = int(max_chunk_size)
        self._secret_values = (api_key,)

    def extract(
        self,
        full_text,
        recorder=None,
        cancel_token=None,
        progress_callback=None,
    ):
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        print("=" * 50)
        print("[模块1] 长文档分块实体抽取")
        chunks = self._split_document(full_text)
        print(f"文档分块完成：共 {len(chunks)} 块")
        if recorder is not None:
            recorder.record_chunks("entity_extraction", chunks)

        all_entities = []
        for index, chunk in enumerate(chunks, start=1):
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            print(f"  抽取第 {index} 块...")
            all_entities.extend(
                self._extract_from_chunk(
                    chunk,
                    recorder=recorder,
                    chunk_index=index - 1,
                )
            )
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            if progress_callback is not None:
                progress_callback(index, len(chunks))

        all_entities.extend(self._extract_normative_entities(full_text))

        entity_map = {}
        for entity in self._filter_invalid_entities(all_entities):
            if entity["name"] in full_text:
                entity_map[entity["name"]] = entity
        for expert_entity in self.expert_entities:
            entity_map.setdefault(expert_entity, {"name": expert_entity, "type": UNKNOWN_TYPE})

        final_entities = sorted(entity_map.values(), key=lambda item: item["name"])
        print(f"有效实体数：{len(final_entities)}")
        if final_entities:
            print(f"实体示例：{final_entities[:10]}")
        return final_entities

    def _split_document(self, text):
        heading_re = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)
        headings = list(heading_re.finditer(text))
        if not headings:
            return [text] if len(text) <= self.max_chunk_size else self._fixed_size_chunks(text)

        segments = []
        preamble = text[:headings[0].start()].strip()
        if preamble:
            segments.append(preamble)
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            section = text[heading.start():end].strip()
            if section:
                segments.append(section)

        chunks = []
        current_chunk = ""
        for segment in segments:
            current_chunk = self._append_segment(chunks, current_chunk, segment)
        if current_chunk:
            chunks.append(current_chunk.strip())
        return chunks

    def _append_segment(self, chunks, current_chunk, segment):
        if not segment:
            return current_chunk
        if len(current_chunk) + len(segment) <= self.max_chunk_size:
            return f"{current_chunk}\n{segment}" if current_chunk else segment
        if current_chunk:
            chunks.append(current_chunk.strip())
        if len(segment) <= self.max_chunk_size:
            return segment
        sub_chunks = self._fixed_size_chunks(segment)
        chunks.extend(sub_chunks[:-1])
        return sub_chunks[-1]

    def _fixed_size_chunks(self, text):
        return [text[i:i + self.max_chunk_size] for i in range(0, len(text), self.max_chunk_size)]

    def _extract_normative_entities(self, text):
        entities = []
        seen = set()
        title_pattern = r"《[^》]{2,80}》"
        code_pattern = (
            r"(?:"
            r"Q[ /]?[A-Z]{1,5}|"
            r"SY[ /]?[Tt]|"
            r"GB|JGJ|NB[ /]?[Tt]|SH[ /]?[Tt]|DL[ /]?[Tt]|AQ"
            r")"
            r"[ \t]*[A-Z]?[ \t]*[0-9][0-9A-Za-z./ \t-]{1,30}[0-9]"
        )
        pattern = re.compile(
            rf"{title_pattern}(?:[ \t]*[（(]?[ \t]*(?:{code_pattern})[ \t]*[）)]?)?"
        )

        for match in pattern.finditer(text):
            name = match.group(0).strip().rstrip("；;，,。.")
            if len(name) < 4 or name in seen:
                continue
            seen.add(name)
            entities.append({"name": name, "type": self.schema.normalize_entity_type(NORMATIVE_ENTITY_TYPE)})
        return entities

    def _build_prompt(self, chunk):
        return f"""你是页岩气工程知识图谱实体抽取专家。
请只从给定文本中抽取真实出现的专业实体，并为每个实体标注实体类型。

【实体类型schema】
{self.schema.render_entity_schema()}

【严格要求】
1. 实体名称必须在原文中原样出现，禁止改写、推断、概括。
2. type 必须来自实体类型schema；无法判断时填“{UNKNOWN_TYPE}”。
3. 不要输出分类标题、章节标题、普通动词、完整句子。
4. 仅输出JSON数组，不要解释。

输出格式：
[
  {{"name": "实体名称", "type": "实体类型"}}
]

文本：
{chunk}
"""

    def _extract_from_chunk(self, chunk, recorder=None, chunk_index=None):
        prompt = self._build_prompt(chunk)
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            raw_response = response.choices[0].message.content
            entities = self._parse_entities(raw_response)
            if recorder is not None:
                recorder.record_llm_call(
                    stage="entity_extraction",
                    prompt=prompt,
                    raw_response=raw_response,
                    parsed=entities,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    metadata={
                        "chunk_type": "entity_extraction",
                        "chunk_index": chunk_index,
                    },
                )
            return entities
        except Exception as exc:
            safe_error = redact_text(str(exc), secrets=self._secret_values)
            print(f"实体抽取失败：{safe_error}")
            if recorder is not None:
                recorder.record_llm_call(
                    stage="entity_extraction",
                    prompt=prompt,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    success=False,
                    error_message=safe_error,
                    metadata={
                        "chunk_type": "entity_extraction",
                        "chunk_index": chunk_index,
                    },
                )
            return []

    def _parse_entities(self, raw_text):
        raw_text = raw_text.strip()
        try:
            match = re.search(r"\[[\s\S]*\]", raw_text)
            payload = match.group(0) if match else raw_text
            data = json.loads(payload)
        except Exception:
            data = self._parse_line_entities(raw_text)

        entities = []
        for item in data:
            if isinstance(item, str):
                name, entity_type = item.strip(), UNKNOWN_TYPE
            elif isinstance(item, dict):
                name = str(item.get("name", "")).strip()
                entity_type = str(item.get("type") or item.get("entity_type") or UNKNOWN_TYPE).strip()
            else:
                continue
            if len(name) >= 2:
                entities.append({"name": name, "type": self.schema.normalize_entity_type(entity_type)})
        return entities

    def _parse_line_entities(self, raw_text):
        entities = []
        for line in raw_text.splitlines():
            line = line.strip().strip("-").strip()
            if not line:
                continue
            parts = re.split(r"[,\t，|]", line)
            entities.append({"name": parts[0].strip(), "type": parts[1].strip() if len(parts) > 1 else UNKNOWN_TYPE})
        return entities

    def _filter_invalid_entities(self, entities):
        invalid_keywords = [
            "实体类型", "关系类型", "分类", "章节", "标题",
            "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.",
        ]
        return [entity for entity in entities if not any(key in entity["name"] for key in invalid_keywords)]
