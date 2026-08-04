import json
import tempfile
import unittest
from pathlib import Path

from kg_extract_build.audit.rule_set import RuleSetError, load_deterministic_rule_set
from kg_extract_build.audit.rules import get_handler
from kg_extract_build.audit.task_library import load_published_task_library


class DeterministicRuleSetTests(unittest.TestCase):
    def test_published_rule_set_covers_every_deterministic_task(self):
        library = load_published_task_library()
        rule_set = load_deterministic_rule_set(library)
        self.assertEqual(rule_set.version, "1.0.2")
        self.assertEqual(set(rule_set.rules), {task.task_id for task in library.tasks if task.route == "deterministic"})
        self.assertEqual(len(rule_set.sha256), 64)

    def test_rejects_missing_or_unregistered_handler(self):
        library = load_published_task_library()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(json.dumps({"rule_set_id": "x", "version": "1", "rules": {task.task_id: {"handler": "unknown"} for task in library.tasks if task.route == "deterministic"}}), encoding="utf-8")
            with self.assertRaises(RuleSetError):
                load_deterministic_rule_set(library, path)

    def test_rejects_schema_invalid_rule_set(self):
        library = load_published_task_library()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit-deterministic-rules.v1.0.0.json"
            path.write_text(json.dumps({"rule_set_id": "x", "version": "1", "rules": []}), encoding="utf-8")
            path.with_name("audit-deterministic-rules.schema.json").write_text(
                Path("docs/audit-task-library/v1/audit-deterministic-rules.schema.json").read_text(encoding="utf-8"), encoding="utf-8"
            )
            with self.assertRaises(RuleSetError):
                load_deterministic_rule_set(library, path)

    def test_handler_registry_is_executable_contract(self):
        self.assertEqual(get_handler("tables").description, "业务表头、业务行与必填值检查")
        with self.assertRaises(ValueError):
            get_handler("not_registered")


if __name__ == "__main__":
    unittest.main()
