import unittest

from kg_extract_build.audit.bindings import build_task_bindings
from kg_extract_build.audit.task_library import load_published_task_library


class AuditTaskLibraryTests(unittest.TestCase):
    def test_loads_the_published_v1_library_and_binds_all_tasks(self):
        library = load_published_task_library()

        self.assertEqual(library.version, "1.0.0")
        self.assertEqual(len(library.tasks), 42)
        self.assertEqual(len(library.sha256), 64)
        self.assertEqual(library.task_by_id("ARR-002").route, "semantic_reasonableness")

        bindings = build_task_bindings(library)
        self.assertEqual(set(bindings), {task.task_id for task in library.tasks})
        self.assertEqual(bindings["ARR-002"].locator_profile, "ordered_steps")
        self.assertEqual(bindings["HSE-002"].handler_key, "jsa_rule")


if __name__ == "__main__":
    unittest.main()
