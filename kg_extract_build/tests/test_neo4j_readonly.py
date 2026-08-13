import unittest

from kg_extract_build.audit.neo4j_readonly import Neo4jReadOnlyGraph


class Record:
    def __init__(self, **values):
        self.values = values

    def data(self):
        return dict(self.values)


class Result:
    def __init__(self, rows=None):
        self.rows = rows or [Record(clue_id="a1", relationship_type="USES", source_document_id="d1", evidence_sentence="source")]

    def __iter__(self):
        return iter(self.rows)


class Session:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        return Result(self.rows)


class Driver:
    def __init__(self, rows=None):
        self.session_instance = Session(rows)
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
        self.assertIn("MATCH (matched:Entity)-[head:HAS_ASSERTION]-(direct:RelationAssertion)", query)
        self.assertIn("UNION", query)
        self.assertIn("DISTINCT", query)
        self.assertIn("1 AS hops", query)
        self.assertIn("2 AS hops", query)
        self.assertNotIn("UNWIND assertions", query)
        self.assertIn("__kg_aggregate", query)
        self.assertIn("aliases", query)
        self.assertIn("-(neighbor:Entity)", query)
        self.assertIn("coalesce(candidate.evidence_sentence,candidate.raw_text,'') AS evidence_sentence", query)
        self.assertEqual(params["relationship_types"], ["USES"])
        self.assertNotRegex(query, r"\b(CREATE|MERGE|SET|DELETE)\b")

    def test_close_closes_driver(self):
        driver = Driver()
        Neo4jReadOnlyGraph(driver).close()
        self.assertTrue(driver.closed)

    def test_query_uses_legacy_evidence_json_when_direct_evidence_is_empty(self):
        driver = Driver([Record(
            clue_id="a1", assertion_id="a1", relationship_type="USES", source_document_id="d1",
            evidence_sentence="", evidence_json=(
                '[{"sentence":"作业人员正确佩戴劳动保护用品。"},'
                '{"sentence":"另一条证据。"}]'
            ),
        )])

        rows = Neo4jReadOnlyGraph(driver).query_clues(
            task_id="HSE-001", query="劳动保护用品", relationship_types=("USES",), max_hops=2,
        )

        self.assertEqual(rows[0]["evidence_sentence"], "作业人员正确佩戴劳动保护用品。")
        query, _ = driver.session_instance.calls[0]
        self.assertIn("candidate.evidence_json AS evidence_json", query)


if __name__ == "__main__":
    unittest.main()
