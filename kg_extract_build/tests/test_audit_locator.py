import unittest

from kg_extract_build.audit.locator import locate_task
from kg_extract_build.audit.models import AuditDocumentBlock, TaskBinding
from kg_extract_build.audit.task_library import load_published_task_library
from kg_extract_build.audit.word_parser import normalize_for_match


def block(block_id, text, section_path=(), *, ordinal=1, block_type="paragraph", source="word/body[1]/paragraph", images=()):
    return AuditDocumentBlock(
        block_id=block_id,
        document_id="doc-1",
        ordinal=ordinal,
        block_type=block_type,
        section_path=section_path,
        source_locator=source,
        raw_text=text,
        normalized_text=normalize_for_match(text),
        image_refs=images,
    )


class AuditLocatorTests(unittest.TestCase):
    def test_locates_ordered_steps_using_task_anchor(self):
        task = load_published_task_library().task_by_id("ARR-002")
        result = locate_task(
            task,
            (block("B1", "4.1 施工顺序安排：作业准备→开工条件确认→电缆敷设"),),
        )

        self.assertEqual(result.status, "located")
        self.assertEqual(result.hits[0].block_id, "B1")
        self.assertIn("施工顺序安排", result.hits[0].matched_locators)

    def test_reports_not_located_without_creating_a_problem(self):
        task = load_published_task_library().task_by_id("HSE-004")
        result = locate_task(task, (block("B1", "这里是一般说明。"),))

        self.assertEqual(result.status, "not_located")
        self.assertEqual(result.hits, ())

    def test_multiple_same_score_sections_are_ambiguous_groups(self):
        task = load_published_task_library().task_by_id("ARR-002")
        result = locate_task(task, (
            block("B1", "施工顺序安排", ("第四章", "4.1 施工顺序安排")),
            block("B2", "施工顺序安排", ("第四章", "4.2 施工顺序安排")),
        ))
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(len(result.evidence_groups), 2)

    def test_cover_and_directory_use_their_dedicated_regions(self):
        library = load_published_task_library()
        cover = locate_task(library.task_by_id("COVER-001"), (block("C", "", ordinal=1, images=("cover",)),), TaskBinding("COVER-001", "cover_region", "deterministic"))
        directory = locate_task(library.task_by_id("DOC-001"), (
            block("T1", "第一章 编制依据\t1", ordinal=2, block_type="toc_entry"),
            block("T2", "附录E\t20", ordinal=3, block_type="toc_entry"),
            block("A", "附录E 实际正文", ordinal=50, block_type="heading"),
        ), TaskBinding("DOC-001", "toc_region", "deterministic"))

        self.assertEqual(cover.status, "located")
        self.assertEqual(directory.evidence_groups[0].anchor_block_id, "T1")
        self.assertEqual(directory.evidence_groups[0].supporting_block_ids, ("T1", "T2"))

    def test_exact_and_shared_appendix_regions_do_not_cross_sources(self):
        library = load_published_task_library()
        blocks = (
            block("B11", "1.1 文件依据", ("第一章", "1.1 文件依据"), ordinal=1, block_type="heading"),
            block("B12", "1.2 其他依据", ("第一章", "1.2 其他依据"), ordinal=2, block_type="heading"),
            block("B13", "现场踏勘", ("第一章", "1.2 其他依据"), ordinal=3),
            block("D", "附录D 设备装置评估表", ("附录D",), ordinal=10, block_type="heading"),
            block("DT", "设备评估内容", ("附录D",), ordinal=11, block_type="table"),
            block("H", "页眉污染", ("附录D",), ordinal=99, source="word/header[1]/paragraph"),
        )
        basis = locate_task(library.task_by_id("BASIS-003"), blocks, TaskBinding("BASIS-003", "exact_section", "deterministic"))
        first = locate_task(library.task_by_id("APPD-001"), blocks, TaskBinding("APPD-001", "shared_appendix_d", "deterministic"))
        second = locate_task(library.task_by_id("APPD-002"), blocks, TaskBinding("APPD-002", "shared_appendix_d", "semantic_reasonableness"))

        self.assertEqual(basis.evidence_groups[0].anchor_block_id, "B12")
        self.assertEqual(first.evidence_groups[0].supporting_block_ids, second.evidence_groups[0].supporting_block_ids)
        self.assertNotIn("H", first.evidence_groups[0].supporting_block_ids)

    def test_prep_006_collects_only_adjacent_personnel_credential_image(self):
        task = load_published_task_library().task_by_id("PREP-006")
        blocks = (
            block("P31", "3.1.1施工人员组织结构", ("第三章", "3.1施工准备", "3.1.1施工人员组织结构"), ordinal=1, block_type="heading"),
            block("NAME", "电工：某某，特种人员证件号：123", ("第三章", "3.1施工准备", "3.1.1施工人员组织结构"), ordinal=2),
            block("P32", "3.2资源配置计划", ("第三章", "3.2资源配置计划"), ordinal=3, block_type="heading"),
            block("EQUIP", "主要设备材料表", ("第三章", "3.2资源配置计划"), ordinal=4, block_type="table"),
            block("PERSON", "施工人员配置", ("第三章", "3.2资源配置计划"), ordinal=5),
            block("TABLE", "专业岗位 | 工种 | 人数\n电工 | | 1", ("第三章", "3.2资源配置计划"), ordinal=6, block_type="table"),
            block("DESC", "电工：某某", ("第三章", "3.2资源配置计划"), ordinal=7),
            block("CARD", "", ("第三章", "3.2资源配置计划"), ordinal=8, images=("credential",)),
            block("P33", "3.3主要工作量", ("第三章", "3.3主要工作量"), ordinal=9, block_type="heading"),
            block("PHOTO", "", ("第三章", "3.3主要工作量"), ordinal=10, images=("work-photo",)),
        )

        result = locate_task(task, blocks, TaskBinding("PREP-006", "person_qualification_composite", "deterministic"))
        support = result.evidence_groups[0].supporting_block_ids
        self.assertEqual(result.status, "located")
        self.assertIn("TABLE", support)
        self.assertIn("CARD", support)
        self.assertNotIn("EQUIP", support)
        self.assertNotIn("PHOTO", support)
        self.assertEqual(support, tuple(sorted(support, key=lambda item: next(block.ordinal for block in blocks if block.block_id == item))))
        self.assertEqual(support.count("CARD"), 1)


if __name__ == "__main__":
    unittest.main()
