import unittest

from kg_extract_build.audit.locator import locate_task
from kg_extract_build.audit.models import AuditDocumentBlock
from kg_extract_build.audit.task_library import load_published_task_library
from kg_extract_build.audit.word_parser import normalize_for_match


def block(block_id, text, section_path=()):
    return AuditDocumentBlock(
        block_id=block_id,
        document_id="doc-1",
        ordinal=1,
        block_type="paragraph",
        section_path=section_path,
        source_locator="word/body[1]/paragraph",
        raw_text=text,
        normalized_text=normalize_for_match(text),
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


if __name__ == "__main__":
    unittest.main()
