import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "kg_schema.example.json"


class SchemaAuditRelationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.relations = {
            item["name"]: item
            for item in payload["relation_types"]
        }

    def test_record_relation_is_unified_as_recorded_in(self):
        self.assertNotIn("HAS_RECORD", self.relations)
        recorded_in = self.relations["RECORDED_IN"]
        self.assertEqual(recorded_in["tail_types"], ["施工记录"])
        self.assertEqual(
            set(recorded_in["head_types"]),
            {
                "施工对象",
                "施工阶段",
                "作业活动",
                "施工参数",
                "风险事件",
                "控制措施",
            },
        )

    def test_operates_on_does_not_overlap_equipment_usage(self):
        self.assertEqual(
            set(self.relations["OPERATES_ON"]["tail_types"]),
            {"施工对象", "环保对象"},
        )
        self.assertEqual(
            self.relations["USES_EQUIPMENT"]["tail_types"],
            ["设备工具"],
        )


if __name__ == "__main__":
    unittest.main()
