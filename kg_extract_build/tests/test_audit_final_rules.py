import unittest
from types import SimpleNamespace

from kg_extract_build.audit.rules.cross_section import conflicting_values, extract_labeled_values, normalize_by_kind
from kg_extract_build.audit.rules.equipment import compare_coverage
from kg_extract_build.audit.rules.appendices import appendix_corpus, missing_regions
from kg_extract_build.audit.task_library import load_published_task_library


class FinalRuleRegressionTests(unittest.TestCase):
    def test_h25a_h2b_location_conflict_is_aggregated_once(self):
        values = [(normalize_by_kind("长宁H25A平台", "location"), "正文"), (normalize_by_kind("H2B井场", "location"), "附录C")]
        self.assertEqual(set(conflicting_values(values)), {"长宁H25A", "H2B"})

    def test_extracts_location_from_heading_and_following_paragraph(self):
        blocks = (
            SimpleNamespace(block_type="heading", raw_text="2.2建设地点", section_path=("第二章 工程概况", "2.2建设地点"), source_locator="word/body[20]/heading"),
            SimpleNamespace(block_type="paragraph", raw_text="长宁H25A平台", section_path=("第二章 工程概况", "2.2建设地点"), source_locator="word/body[21]/paragraph"),
        )

        values = extract_labeled_values(blocks, ("建设地点", "作业场所", "施工地点"), "location")

        self.assertEqual(values, [("长宁H25A", "word/body[21]/paragraph")])

    def test_equipment_coverage_and_quantity_comparison(self):
        evidence = (
            {"section_path": ["3.2资源配置计划"], "table_json": {"rows": [["名称", "单位", "数量"], ["常用工具（锄头、铲子、扳手）", "套", "3"], ["电焊机", "台", "2"]]}},
            {"section_path": ["附录D"], "table_json": {"rows": [["名称", "数量"], ["锄头", ""], ["铲子", ""], ["扳手", ""], ["电焊机", "1"]]}},
        )
        missing, mismatches = compare_coverage(evidence)
        self.assertEqual(missing, ())
        self.assertEqual(mismatches, (("电焊机", "2", "1"),))

    def test_extracts_location_from_table_label_and_adjacent_value(self):
        blocks = (SimpleNamespace(block_type="table", raw_text="", section_path=("附录C",), source_locator="word/body[90]/table[1]", table_json={"rows": [["作业场所", "长宁H2B平台"]]}),)
        self.assertEqual(extract_labeled_values(blocks, ("作业场所",), "location"), [("长宁H2B", "word/body[90]/table[1]")])

    def test_appendix_b_vertical_labels_are_normalized(self):
        corpus = appendix_corpus(({"raw_text": "施工作业人员\nHSE\n培训要点\n参 加 培 训 人 员 确 认", "table_json": None},))
        self.assertEqual(missing_regions(corpus, ("施工作业人员HSE培训要点", "参加培训人员确认")), ())

    def test_v111_approval_structure_does_not_require_approval_opinion(self):
        library = load_published_task_library("docs/audit-task-library/v1/audit-task-library.v1.1.1.json")
        required = library.task_by_id("APPA-002").required
        self.assertNotIn("审批意见填写区域", required)
        self.assertIn("签字日期位置", required)

    def test_approval_form_signature_label_accepts_sign_name(self):
        corpus = appendix_corpus(({"raw_text": "项目负责人： 单位名称： 批准人： 安全管理人员： 签名：……年……月……日", "table_json": None},))
        self.assertTrue(("签名" in corpus or "签字" in corpus) and all(value in corpus for value in ("年", "月", "日")))


if __name__ == "__main__":
    unittest.main()
