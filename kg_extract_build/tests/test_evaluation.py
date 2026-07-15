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
    def test_loads_adjudicated_document_file_with_title_and_chinese_name_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "adjudicated_gold.json"
            payload = {"document": {"title": "??H3????????"}, "triplets": [{"head_name": "??????", "head_type": "????", "relation": "HAS_STAGE", "tail_name": "????", "tail_type": "????"}]}
            file_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            annotations = load_gold_annotations(file_path)
        self.assertEqual(set(annotations.documents), {"??H3????????"})
        self.assertEqual(annotations.triplet_count, 1)
        self.assertEqual(annotations.errors, [])

    def test_records_error_when_object_gold_omits_triplets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); doc = root / "document_a"; doc.mkdir()
            (doc / "incomplete.json").write_text(json.dumps({"document": {"title": "document_a"}}), encoding="utf-8")
            annotations = load_gold_annotations(root)
        self.assertEqual(annotations.documents, {})
        self.assertEqual(len(annotations.errors), 1)
        self.assertIn("triplets", annotations.errors[0]["error"])

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
        self.assertAlmostEqual(
            result.overall["selected_evidence_coverage"].value, 0.5
        )
        self.assertAlmostEqual(
            result.overall["selected_evidence_tail_absence_rate"].value, 0.5
        )

    def test_retrieval_evidence_does_not_fall_back_to_document_text(self):
        triplet = ("A", "类型1", "REL", "B", "类型2")
        result = evaluate_documents(
            model={"文档A": [triplet]},
            gold={"文档A": [triplet]},
            documents={"文档A": "A 和 B 同时出现在全文。"},
            evidence={"文档A": {triplet: ["A 的另一条检索句。"]}},
            schema=None,
        )

        self.assertAlmostEqual(
            result.overall["selected_evidence_coverage"].value, 0.0
        )
        self.assertAlmostEqual(
            result.overall["selected_evidence_tail_absence_rate"].value, 1.0
        )

    def test_canonical_triplet_uses_gold_aliases_and_ids(self):
        model_triplet = ("井口装置", "设备设施", "USES", "电缆线", "施工对象")
        result = evaluate_documents(
            model={"文档A": [model_triplet]},
            gold={"文档A": [("井口装置", "设备设施", "USES", "电缆", "施工对象")]},
            documents={"文档A": ""}, evidence={"文档A": {}},
            canonical_entities={"文档A": [
                {"canonical_id": "EQ001", "canonical_name": "井口装置", "entity_type": "设备设施", "names": ["井口装置"]},
                {"canonical_id": "OBJ003", "canonical_name": "电缆", "entity_type": "施工对象", "names": ["电缆", "电缆线", "电缆线"]},
            ]},
            canonical_gold_triplets={"文档A": [("EQ001", "USES", "OBJ003")]},
        )
        self.assertAlmostEqual(result.overall["triplet_f1"].value, 0.0)
        self.assertAlmostEqual(result.overall["canonical_triplet_f1"].value, 1.0)
        self.assertAlmostEqual(result.overall["canonical_entity_mapping_rate"].value, 1.0)
        self.assertEqual(len(result.entity_alignments), 2)

    def test_evaluation_matches_unique_preprocessing_name_variants(self):
        triplet = ("A", "类型1", "REL", "B", "类型2")
        result = evaluate_documents(
            model={"长宁H3_待评估": [triplet]},
            gold={"长宁H3_预处理": [triplet]},
            documents={"长宁H3_待评估": ""},
            evidence={"长宁H3_待评估": {triplet: ["B"]}},
        )
        self.assertEqual(result.matched_documents, ["长宁H3_待评估"])
        self.assertEqual(result.missing_gold_documents, [])
        self.assertEqual(result.extra_gold_documents, [])
        self.assertAlmostEqual(result.overall["triplet_f1"].value, 1.0)

from kg_extract_build.evaluation import GoldAnnotations, build_preview


class EvaluationPreviewTests(unittest.TestCase):
    def test_preview_reports_matching_and_existing_evaluations(self):
        gold = GoldAnnotations(
            root=Path("D:/gold"),
            documents={
                "文档A": [("A", "T", "R", "B", "T")],
                "文档C": [("C", "T", "R", "D", "T")],
            },
            errors=[{"path": "bad.json", "error": "broken"}],
        )
        preview = build_preview(
            model_documents={"文档A", "文档B"},
            gold=gold,
            model_triplet_count=3,
            existing_evaluations=[{"evaluation_id": "e1"}],
        )
        self.assertEqual(preview["model_document_count"], 2)
        self.assertEqual(preview["gold_document_count"], 2)
        self.assertEqual(preview["matched_document_count"], 1)
        self.assertEqual(preview["missing_gold_documents"], ["文档B"])
        self.assertEqual(preview["extra_gold_documents"], ["文档C"])
        self.assertEqual(preview["gold_triplet_count"], 2)
        self.assertEqual(preview["model_triplet_count"], 3)
        self.assertEqual(preview["parse_error_count"], 1)
        self.assertTrue(preview["calculation_blocked"])
        self.assertEqual(preview["existing_evaluation_count"], 1)
