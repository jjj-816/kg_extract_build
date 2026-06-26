import json

from .settings import UNKNOWN_TYPE


class KGSchema:
    def __init__(self, schema_path):
        self.schema_path = schema_path
        self.entity_types = []
        self.relation_types = []
        self.entity_type_names = set()
        self.relation_type_names = set()
        self.relation_rules = {}
        self.load()

    def load(self):
        if not self.schema_path.exists():
            print(f"未找到schema文件：{self.schema_path}，将使用非schema约束模式")
            return

        with self.schema_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self.entity_types = self._normalize_items(data.get("entity_types", []))
        self.relation_types = self._normalize_items(data.get("relation_types", []))
        self.entity_type_names = {item["name"] for item in self.entity_types}
        self.relation_type_names = {item["name"] for item in self.relation_types}

        for item in self.relation_types:
            self.relation_rules[item["name"]] = {
                "head_types": set(item.get("head_types", [])),
                "tail_types": set(item.get("tail_types", [])),
            }

        print(f"已加载schema：{len(self.entity_types)}类实体，{len(self.relation_types)}类关系")

    def _normalize_items(self, items):
        normalized = []
        for item in items:
            if isinstance(item, str):
                normalized.append({"name": item, "description": "", "examples": []})
            elif isinstance(item, dict) and item.get("name"):
                normalized.append({
                    "name": item["name"],
                    "cn_name": item.get("cn_name", ""),
                    "description": item.get("description", ""),
                    "examples": item.get("examples", []),
                    "head_types": item.get("head_types", []),
                    "tail_types": item.get("tail_types", []),
                })
        return normalized

    def render_entity_schema(self):
        if not self.entity_types:
            return "未提供实体类型schema。"
        lines = []
        for item in self.entity_types:
            desc = f"：{item['description']}" if item.get("description") else ""
            examples = item.get("examples") or []
            example_text = f"；示例：{', '.join(examples[:6])}" if examples else ""
            lines.append(f"- {item['name']}{desc}{example_text}")
        return "\n".join(lines)

    def render_relation_schema(self):
        if not self.relation_types:
            return "未提供关系类型schema。"
        lines = []
        for item in self.relation_types:
            cn_name = f"（{item['cn_name']}）" if item.get("cn_name") else ""
            desc = f"：{item['description']}" if item.get("description") else ""
            head = item.get("head_types") or []
            tail = item.get("tail_types") or []
            scope = f"；头实体类型：{', '.join(head) or '不限'}；尾实体类型：{', '.join(tail) or '不限'}"
            lines.append(f"- {item['name']}{cn_name}{desc}{scope}")
        return "\n".join(lines)

    def allowed_relation_items(self, head_type):
        if not self.relation_types:
            return []
        if not head_type or head_type == UNKNOWN_TYPE:
            return self.relation_types

        allowed_items = []
        for item in self.relation_types:
            head_types = set(item.get("head_types") or [])
            if not head_types or head_type in head_types:
                allowed_items.append(item)
        return allowed_items

    def render_allowed_relation_schema(self, head_type):
        allowed_items = self.allowed_relation_items(head_type)
        if not allowed_items:
            return "No allowed relations for this head_type. Return []."

        lines = []
        for item in allowed_items:
            tail_types = item.get("tail_types") or []
            tail_text = "|".join(tail_types) if tail_types else "ANY"
            lines.append(f"- {item['name']} -> {tail_text}")
        return "\n".join(lines)

    def render_allowed_tail_types(self, head_type):
        tail_types = []
        seen = set()
        for item in self.allowed_relation_items(head_type):
            for tail_type in item.get("tail_types") or []:
                if tail_type not in seen:
                    tail_types.append(tail_type)
                    seen.add(tail_type)
        if not tail_types:
            return UNKNOWN_TYPE
        return ", ".join(tail_types + [UNKNOWN_TYPE])

    def normalize_entity_type(self, entity_type):
        if not entity_type:
            return UNKNOWN_TYPE
        if not self.entity_type_names:
            return entity_type
        return entity_type if entity_type in self.entity_type_names else UNKNOWN_TYPE

    def normalize_relation(self, relation):
        if not self.relation_type_names:
            return relation
        return relation if relation in self.relation_type_names else ""

    def is_relation_allowed(self, relation, head_type=None, tail_type=None):
        if not self.relation_type_names:
            return True
        if relation not in self.relation_type_names:
            return False

        rule = self.relation_rules.get(relation, {})
        head_types = rule.get("head_types") or set()
        tail_types = rule.get("tail_types") or set()
        if head_types and head_type and head_type != UNKNOWN_TYPE and head_type not in head_types:
            return False
        if tail_types and tail_type and tail_type != UNKNOWN_TYPE and tail_type not in tail_types:
            return False
        return True
