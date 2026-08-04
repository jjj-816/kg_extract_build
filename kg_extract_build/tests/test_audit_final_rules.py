import unittest

from kg_extract_build.audit.rules.cross_section import conflicting_values, normalize_by_kind
from kg_extract_build.audit.rules.equipment import compare_coverage


class FinalRuleRegressionTests(unittest.TestCase):
    def test_h25a_h2b_location_conflict_is_aggregated_once(self):
        values = [(normalize_by_kind("长宁H25A平台", "location"), "正文"), (normalize_by_kind("H2B井场", "location"), "附录C")]
        self.assertEqual(set(conflicting_values(values)), {"长宁H25A", "H2B"})

    def test_equipment_coverage_and_quantity_comparison(self):
        evidence = (
            {"section_path": ["3.2资源配置计划"], "table_json": {"rows": [["名称", "单位", "数量"], ["常用工具（锄头、铲子、扳手）", "套", "3"], ["电焊机", "台", "2"]]}},
            {"section_path": ["附录D"], "table_json": {"rows": [["名称", "数量"], ["锄头", ""], ["铲子", ""], ["扳手", ""], ["电焊机", "1"]]}},
        )
        missing, mismatches = compare_coverage(evidence)
        self.assertEqual(missing, ())
        self.assertEqual(mismatches, (("电焊机", "2", "1"),))


if __name__ == "__main__":
    unittest.main()
