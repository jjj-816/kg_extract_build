"""确定性规则集加载、完整性校验与版本快照。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .rules import REGISTERED_HANDLERS
from .settings import AUDIT_DETERMINISTIC_RULE_SET_PATH


class RuleSetError(ValueError):
    pass


@dataclass(frozen=True)
class DeterministicRuleSet:
    rule_set_id: str
    version: str
    sha256: str
    source_path: Path
    rules: dict[str, dict]

    def snapshot(self) -> dict[str, str]:
        return {"id": self.rule_set_id, "version": self.version, "sha256": self.sha256}


def load_deterministic_rule_set(task_library, path: str | Path | None = None) -> DeterministicRuleSet:
    source = Path(path or AUDIT_DETERMINISTIC_RULE_SET_PATH).expanduser().resolve()
    if not source.is_file():
        raise RuleSetError(f"确定性规则集不存在：{source}")
    raw = source.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuleSetError("确定性规则集不是有效 UTF-8 JSON") from exc
    schema_path = source.with_name("audit-deterministic-rules.schema.json")
    if not schema_path.is_file():
        raise RuleSetError(f"确定性规则集 Schema 不存在：{schema_path}")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        import jsonschema
        jsonschema.Draft202012Validator(schema).validate(data)
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError, jsonschema.SchemaError) as exc:
        raise RuleSetError(f"确定性规则集未通过 Schema 校验：{exc.message if hasattr(exc, 'message') else exc}") from exc
    if not isinstance(data.get("rule_set_id"), str) or not isinstance(data.get("version"), str):
        raise RuleSetError("规则集缺少 rule_set_id 或 version")
    rules = data.get("rules")
    if not isinstance(rules, dict):
        raise RuleSetError("规则集 rules 必须是对象")
    deterministic = {task.task_id for task in task_library.tasks if task.route == "deterministic"}
    missing = sorted(deterministic - set(rules))
    unexpected = sorted(set(rules) - deterministic)
    if missing or unexpected:
        raise RuleSetError(f"规则集与确定性任务不一致：缺少 {missing}；多余 {unexpected}")
    for task_id, rule in rules.items():
        if not isinstance(rule, dict) or not isinstance(rule.get("handler"), str):
            raise RuleSetError(f"规则 {task_id} 缺少 handler")
        if rule["handler"] not in REGISTERED_HANDLERS:
            raise RuleSetError(f"规则 {task_id} 引用了未注册处理器：{rule['handler']}")
    return DeterministicRuleSet(data["rule_set_id"], data["version"], hashlib.sha256(raw).hexdigest().upper(), source, rules)
