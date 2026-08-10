import unittest

from kg_extract_build.audit.persistence import MySQLAuditStore


class PersistenceContractTests(unittest.TestCase):
    def test_persistence_exposes_append_only_review_and_publish_operations(self):
        self.assertTrue(callable(MySQLAuditStore.append_human_review))
        self.assertTrue(callable(MySQLAuditStore.publish_report))


if __name__ == "__main__":
    unittest.main()
