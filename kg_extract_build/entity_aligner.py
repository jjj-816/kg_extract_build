import json
import re
import time
from difflib import SequenceMatcher

import numpy as np
from openai import OpenAI

from .settings import UNKNOWN_TYPE, VECTOR_MODEL_PATH


GENERIC_ENTITY_NAMES = {
    "设备",
    "设备装置",
    "施工设备",
    "施工机具",
    "机具",
    "工具",
    "工具用具",
    "工器具",
    "常用工具",
    "机械设备",
    "机械和电器设备",
    "用电设备",
    "用电设施",
    "应急所需的设备",
    "应急救援器材",
    "现场",
    "施工现场",
    "施工作业现场",
    "作业现场",
    "作业场所",
    "本井场",
    "事故现场",
    "场站",
    "材料",
    "人员",
    "措施",
    "安全措施",
    "控制措施",
    "风险",
    "隐患",
}
GENERIC_ENTITY_KEYS = {
    re.sub(r"[\s\-_（）()\[\]【】《》“”\"']", "", name.lower())
    for name in GENERIC_ENTITY_NAMES
}


class EntityAligner:
    def __init__(
        self,
        api_key,
        base_url,
        model_name,
        vector_model_path=VECTOR_MODEL_PATH,
        edit_threshold=0.72,
        semantic_threshold=0.82,
        max_group_size=20,
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model_name
        self.vector_model_path = vector_model_path
        self.edit_threshold = edit_threshold
        self.semantic_threshold = semantic_threshold
        self.max_group_size = max_group_size
        self._embedding_model = None
        self._embedding_model_load_failed = False

    def align(self, entities, source_type="case", recorder=None):
        if not entities:
            return [], {}

        unique_entities = self._deduplicate_entities(entities, source_type)
        candidate_groups = self._build_candidate_groups(unique_entities)
        print(f"[实体对齐] 初步候选集合数：{len(candidate_groups)}")

        alias_to_standard = {}
        consumed = set()
        aligned_entities = []

        for group in candidate_groups:
            if len(group) <= 1:
                continue

            decision = self._judge_group(group, recorder=recorder)
            same_groups = decision.get("same_groups", [])
            for same_group in same_groups:
                members = self._valid_members(same_group.get("members", []), group)
                if len(members) < 2:
                    continue
                standard_name = same_group.get("standard_name") or self._choose_standard_name(members)
                standard_entity = self._entity_by_name(standard_name, members) or self._best_entity(members)
                standard_name = standard_entity["name"]
                if not self._is_safe_same_group(members, standard_name):
                    continue
                aliases = sorted({item["name"] for item in members})
                aligned_entities.append({
                    "name": standard_name,
                    "type": standard_entity.get("type", UNKNOWN_TYPE),
                    "aliases": aliases,
                    "source_type": standard_entity.get("source_type", source_type),
                })
                for alias in aliases:
                    alias_to_standard[alias] = standard_name
                consumed.update(aliases)

        for entity in unique_entities:
            name = entity["name"]
            if name in consumed:
                continue
            aligned_entities.append({
                "name": name,
                "type": entity.get("type", UNKNOWN_TYPE),
                "aliases": [name],
                "source_type": entity.get("source_type", source_type),
            })
            alias_to_standard[name] = name

        aligned_entities = self._deduplicate_aligned(aligned_entities)
        print(f"[实体对齐] 对齐前实体数：{len(unique_entities)}，对齐后标准实体数：{len(aligned_entities)}")
        return aligned_entities, alias_to_standard

    def _deduplicate_entities(self, entities, source_type):
        entity_map = {}
        for entity in entities:
            name = str(entity.get("name", "")).strip()
            if not name:
                continue
            current = {
                "name": name,
                "type": entity.get("type", UNKNOWN_TYPE),
                "source_type": entity.get("source_type", source_type),
            }
            if name not in entity_map or self._standard_score(current) > self._standard_score(entity_map[name]):
                entity_map[name] = current
        return list(entity_map.values())

    def _build_candidate_groups(self, entities):
        parent = list(range(len(entities)))

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left, right):
            root_left, root_right = find(left), find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        buckets = {}
        for index, entity in enumerate(entities):
            for key in self._blocking_keys(entity["name"], entity.get("type", UNKNOWN_TYPE)):
                buckets.setdefault(key, []).append(index)

        compared = set()
        for indices in buckets.values():
            if len(indices) < 2:
                continue
            for i, left in enumerate(indices):
                for right in indices[i + 1:]:
                    pair = (min(left, right), max(left, right))
                    if pair in compared:
                        continue
                    compared.add(pair)
                    if self._is_candidate_pair(entities[left], entities[right]):
                        union(left, right)

        groups = {}
        for index in range(len(entities)):
            groups.setdefault(find(index), []).append(entities[index])
        return self._split_large_groups([group for group in groups.values() if len(group) > 1])

    def _blocking_keys(self, name, entity_type):
        normalized = self._normalize_name(name)
        keys = set()
        for char in normalized:
            keys.add(f"{entity_type}:c:{char}")
        for i in range(max(0, len(normalized) - 1)):
            keys.add(f"{entity_type}:b:{normalized[i:i + 2]}")
        return keys

    def _is_candidate_pair(self, left, right):
        left_type = left.get("type", UNKNOWN_TYPE)
        right_type = right.get("type", UNKNOWN_TYPE)
        if left_type != right_type and UNKNOWN_TYPE not in {left_type, right_type}:
            return False

        left_name = self._normalize_name(left["name"])
        right_name = self._normalize_name(right["name"])
        if not left_name or not right_name:
            return False
        if left_name in right_name or right_name in left_name:
            return True
        if SequenceMatcher(None, left_name, right_name).ratio() >= self.edit_threshold:
            return True
        return self._semantic_similarity(left["name"], right["name"]) >= self.semantic_threshold

    def _semantic_similarity(self, left_name, right_name):
        model = self._load_embedding_model()
        if model is None:
            return 0.0
        embeddings = model.encode([left_name, right_name], convert_to_numpy=True)
        left_vec, right_vec = embeddings[0], embeddings[1]
        denominator = np.linalg.norm(left_vec) * np.linalg.norm(right_vec)
        if denominator == 0:
            return 0.0
        return float(np.dot(left_vec, right_vec) / denominator)

    def _load_embedding_model(self):
        if self._embedding_model is not None:
            return self._embedding_model
        if self._embedding_model_load_failed:
            return None
        if not self.vector_model_path:
            return None
        try:
            from sentence_transformers import SentenceTransformer

            self._embedding_model = SentenceTransformer(str(self.vector_model_path))
        except Exception as exc:
            print(f"[实体对齐] 语义相似度模型加载失败，将仅使用编辑距离：{exc}")
            self._embedding_model_load_failed = True
            self._embedding_model = None
        return self._embedding_model

    def _split_large_groups(self, groups):
        split_groups = []
        for group in groups:
            if len(group) <= self.max_group_size:
                split_groups.append(group)
                continue
            sorted_group = sorted(group, key=lambda item: self._normalize_name(item["name"]))
            for start in range(0, len(sorted_group), self.max_group_size):
                chunk = sorted_group[start:start + self.max_group_size]
                if len(chunk) > 1:
                    split_groups.append(chunk)
        return split_groups

    def _judge_group(self, group, recorder=None):
        prompt = self._build_prompt(group)
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                extra_body={"thinking": {"type": "disabled"}},
            )
            raw_response = response.choices[0].message.content
            decision = self._parse_decision(raw_response)
            if recorder is not None:
                recorder.record_llm_call(
                    stage="entity_alignment",
                    prompt=prompt,
                    raw_response=raw_response,
                    parsed=decision,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    metadata={
                        "candidate_entities": [
                            entity["name"] for entity in group
                        ]
                    },
                )
            return decision
        except Exception as exc:
            print(f"[实体对齐] LLM判断失败，使用规则兜底：{exc}")
            decision = self._fallback_decision(group)
            if recorder is not None:
                recorder.record_llm_call(
                    stage="entity_alignment",
                    prompt=prompt,
                    parsed=decision,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    success=False,
                    error_message=str(exc),
                    metadata={
                        "candidate_entities": [
                            entity["name"] for entity in group
                        ],
                        "fallback": "rule",
                    },
                )
            return decision

    def _build_prompt(self, group):
        items = [
            {
                "name": entity["name"],
                "type": entity.get("type", UNKNOWN_TYPE),
                "source_type": entity.get("source_type", "case"),
            }
            for entity in group
        ]
        return f"""你是页岩气工程知识图谱实体对齐专家。请判断候选集合中的实体是否指向同一对象。

判定类别只能使用：
1. SAME：同一实体，可以合并。
2. DIFFERENT：不同实体，不合并。

实体对齐不是主题聚类。只有在多数上下文中可以互换的实体，才允许合并。

以下情况必须判定为 DIFFERENT，禁止合并：
1. 上下位关系，例如“设备”和“发电机”、“施工现场”和“井口”。
2. 部分-整体关系，例如“井站”和“井口”、“设备装置”和“电源导线”。
3. 相关但不同，例如“应急救援器材”和“发电机”、“施工现场”和“事故现场”。
4. 同类但不同，例如“发电机”和“电源导线”、“施工车辆”和“强制通风设备”。
5. 泛称和具体实体，例如“设备”“机具”“现场”“人员”“措施”与任何具体实体。

标准名称选择优先级：
1. 规范、标准、制度文件中的名称优先。
2. 更完整、歧义更少的名称优先。
3. 领域内更常用的术语优先。
4. 不使用简称作为标准名。
5. 不使用带具体项目、具体时间、具体编号的名称作为通用标准名。

候选实体：
{json.dumps(items, ensure_ascii=False, indent=2)}

仅输出JSON对象，不要解释。格式：
{{
  "same_groups": [
    {{"members": ["实体A", "实体B"], "standard_name": "标准名称"}}
  ],
  "different": ["实体C"]
}}
"""
    def _parse_decision(self, raw_text):
        try:
            match = re.search(r"\{[\s\S]*\}", raw_text.strip())
            payload = match.group(0) if match else raw_text
            data = json.loads(payload)
        except Exception:
            return {"same_groups": [], "different": []}
        return {
            "same_groups": data.get("same_groups", []) if isinstance(data.get("same_groups", []), list) else [],
            "different": data.get("different", []) if isinstance(data.get("different", []), list) else [],
        }

    def _fallback_decision(self, group):
        strong_groups = []
        used = set()
        for i, left in enumerate(group):
            if left["name"] in used:
                continue
            members = [left]
            for right in group[i + 1:]:
                if SequenceMatcher(None, self._normalize_name(left["name"]), self._normalize_name(right["name"])).ratio() >= 0.9:
                    members.append(right)
            if len(members) > 1:
                standard_name = self._choose_standard_name(members)
                if not self._is_safe_same_group(members, standard_name):
                    continue
                used.update(item["name"] for item in members)
                strong_groups.append({
                    "members": [item["name"] for item in members],
                    "standard_name": standard_name,
                })
        return {"same_groups": strong_groups, "different": []}

    def _valid_members(self, names, group):
        by_name = {entity["name"]: entity for entity in group}
        return [by_name[name] for name in names if name in by_name]

    def _entity_by_name(self, name, entities):
        for entity in entities:
            if entity["name"] == name:
                return entity
        return None

    def _best_entity(self, entities):
        return max(entities, key=self._standard_score)

    def _choose_standard_name(self, entities):
        return self._best_entity(entities)["name"]

    def _is_safe_same_group(self, members, standard_name):
        member_names = [item["name"] for item in members]
        if self._is_generic_name(standard_name) and len(set(member_names)) > 1:
            return False
        if any(self._is_generic_name(name) for name in member_names) and len(set(member_names)) > 1:
            return False
        return True

    def _standard_score(self, entity):
        name = entity["name"]
        score = len(name)
        if entity.get("source_type") == "spec":
            score += 20
        if self._is_generic_name(name):
            score -= 30
        if self._looks_like_project_specific(name):
            score -= 12
        if self._looks_like_abbreviation(name):
            score -= 8
        return score

    def _looks_like_project_specific(self, name):
        return bool(re.search(r"\d{2,}|井|标段|项目|工程|20\d{2}|19\d{2}", name))

    def _looks_like_abbreviation(self, name):
        return len(name) <= 2 or bool(re.fullmatch(r"[A-Za-z0-9]+", name))

    def _is_generic_name(self, name):
        normalized = self._normalize_name(name)
        return normalized in GENERIC_ENTITY_KEYS

    def _normalize_name(self, name):
        return re.sub(r"[\s\-_（）()\[\]【】《》“”\"']", "", name.lower())

    def _deduplicate_aligned(self, aligned_entities):
        entity_map = {}
        for entity in aligned_entities:
            name = entity["name"]
            if name not in entity_map:
                entity_map[name] = entity
                continue
            aliases = set(entity_map[name].get("aliases", [])) | set(entity.get("aliases", []))
            entity_map[name]["aliases"] = sorted(aliases)
        return sorted(entity_map.values(), key=lambda item: item["name"])
