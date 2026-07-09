import json
import sys
import tempfile
import unittest
from pathlib import Path


TEST_PARENT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = TEST_PARENT.parent if TEST_PARENT.name == "kg_extract_build" else TEST_PARENT
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from kg_extract_build.evaluation import compute_gold_hash, load_gold_annotations


class EvaluationGoldLoadingTests(unittest.TestCase):
    def test_loads_debug_object_and_array_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "高处作业"
            doc.mkdir()
            (doc / "高处.json").write_text(
                json.dumps(
                    {
                        "entity": "高处",
                        "triplets": [
                            {
                                "head": "《高处作业分级》GB/T 3608-2008",
                                "head_type": "规范条款",
                                "relation": "REGULATES",
                                "tail": "高处",
                                "tail_type": "作业活动",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (doc / "安全带.json").write_text(
                json.dumps(
                    [
                        {
                            "head": "安全带",
                            "head_type": "设备设施",
                            "relation": "USED_FOR",
                            "tail": "高处作业",
                            "tail_type": "作业活动",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            annotations = load_gold_annotations(root)

        self.assertEqual(set(annotations.documents), {"高处作业"})
        self.assertEqual(len(annotations.documents["高处作业"]), 2)
        self.assertEqual(annotations.errors, [])

    def test_records_parse_errors_without_stopping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "文档A"
            doc.mkdir()
            (doc / "broken.json").write_text("{", encoding="utf-8")

            annotations = load_gold_annotations(root)

        self.assertEqual(annotations.documents, {})
        self.assertEqual(len(annotations.errors), 1)
        self.assertIn("broken.json", annotations.errors[0]["path"])

    def test_gold_hash_changes_when_content_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "文档A"
            doc.mkdir()
            file_path = doc / "标注.json"
            file_path.write_text("[]", encoding="utf-8")
            first = compute_gold_hash(root)
            file_path.write_text(
                json.dumps([{"head": "A"}], ensure_ascii=False),
                encoding="utf-8",
            )
            second = compute_gold_hash(root)

        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()

from kg_extract_build.evaluation import compute_prf, evaluate_documents


class EvaluationMetricTests(unittest.TestCase):
    def test_compute_prf_uses_strict_set_matching(self):
        score = compute_prf({("A",), ("B",)}, {("A",), ("C",)})
        self.assertEqual(score.true_positive, 1)
        self.assertEqual(score.false_positive, 1)
        self.assertEqual(score.false_negative, 1)
        self.assertAlmostEqual(score.precision, 0.5)
        self.assertAlmostEqual(score.recall, 0.5)
        self.assertAlmostEqual(score.f1, 0.5)

    def test_evaluate_documents_computes_core_metrics(self):
        model = {
            "文档A": [
                ("A", "类型1", "REL", "B", "类型2"),
                ("A", "类型1", "REL", "C", "类型2"),
            ]
        }
        gold = {"文档A": [("A", "类型1", "REL", "B", "类型2")]}
        result = evaluate_documents(
            model=model,
            gold=gold,
            documents={"文档A": "A 和 B 是原文实体。"},
            evidence={"文档A": {model["文档A"][0]: ["A 和 B 是原文实体。"]}},
            schema=None,
        )
        self.assertAlmostEqual(result.overall["triplet_precision"].value, 0.5)
        self.assertAlmostEqual(result.overall["triplet_recall"].value, 1.0)
        self.assertAlmostEqual(result.overall["evidence_coverage"].value, 0.5)
        self.assertAlmostEqual(result.overall["hallucination_rate"].value, 0.5)
