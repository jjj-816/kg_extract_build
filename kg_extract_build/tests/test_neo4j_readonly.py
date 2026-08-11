import unittest

from kg_extract_build.audit.neo4j_readonly import Neo4jReadOnlyGraph


class Record:
    def __init__(self, **values):
        self.values = values

    def data(self):
        return dict(self.values)


class Result:
    def __iter__(self):
        return iter([Record(clue_id="a1", relationship_type="USES", source_document_id="d1", evidence_sentence="source")])


class Session:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        return Result()


class Driver:
    def __init__(self):
        self.session_instance = Session()
        self.closed = False

    def session(self, **kwargs):
        return self.session_instance

    def close(self):
        self.closed = True


class Neo4jReadOnlyTests(unittest.TestCase):
    def test_query_is_bounded_and_read_only(self):
        driver = Driver()
        graph = Neo4jReadOnlyGraph(driver)
        rows = graph.query_clues(task_id="HSE-001", query="pump", relationship_types=("USES",), max_hops=2)
        self.assertEqual(rows[0]["clue_id"], "a1")
        query, params = driver.session_instance.calls[0]
        self.assertIn("2..8", query)
        self.assertIn("__kg_aggregate", query)
        self.assertEqual(params["relationship_types"], ["USES"])
        self.assertNotRegex(query, r"\b(CREATE|MERGE|SET|DELETE)\b")

    def test_close_closes_driver(self):
        driver = Driver()
        Neo4jReadOnlyGraph(driver).close()
        self.assertTrue(driver.closed)


if __name__ == "__main__":
    unittest.main()
