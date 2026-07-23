import json
import os
import unittest
from pathlib import Path

from kg_extract_build.neo4j_graph import (
    Neo4jGraphSynchronizer,
    Neo4jSettings,
    _canonical,
    normalize_entity_name,
)


class _Result:
    def __init__(self, count=0):
        self.count = count

    def single(self):
        return {"count": self.count}


class _Transaction:
    def __init__(self, graph):
        self.graph = graph
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        if "WHERE a.assertion_id IN $ids" in query:
            return _Result(
                sum(assertion_id in self.graph.assertions for assertion_id in params["ids"])
            )
        if "DETACH DELETE a" in query:
            removed = [
                assertion_id
                for assertion_id, assertion in self.graph.assertions.items()
                if assertion["metadata"]["run_id"] == params["run_id"]
                and assertion_id not in params["ids"]
            ]
            for assertion_id in removed:
                self.graph.remove_assertion(assertion_id)
            return _Result(len(removed))
        if "MATCH (old)-[h:HAS_ASSERTION" in query:
            self.graph.migrate("head", params["entities"])
        elif "MATCH (a)-[o:OBJECT" in query:
            self.graph.migrate("tail", params["entities"])
        elif "coalesce(old.aliases,[]) + coalesce(old.aliases,[])" in query:
            raise AssertionError("invalid alias migration query")
        elif "coalesce(old.aliases,[]) + [old.name]" in query:
            self.graph.merge_old_aliases(params["entities"])
        elif "MERGE (a:RelationAssertion" in query:
            self.graph.upsert_assertions(params["items"])
        elif "SET h.aliases=CASE" in query:
            self.graph.add_raw_aliases(params["items"])
        elif "WHERE r.__kg_aggregate = true DELETE r" in query:
            self.graph.aggregates.clear()
        elif "AND NOT (old)--() DELETE old" in query:
            self.graph.delete_migrated_orphans(params["entities"])
        elif "MERGE (h)-[r:" in query:
            self.graph.rebuild_aggregate(params["relation"])
        if "WHERE r.__kg_aggregate=true RETURN count(r)" in query:
            return _Result(len(self.graph.aggregates))
        return _Result()


class _Session:
    def __init__(self, transaction, graph):
        self.transaction = transaction
        self.graph = graph
        self.execute_write_calls = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True
        return False

    def run(self, query, **_params):
        if "MATCH (e:Entity)" in query:
            return [
                {"entity_type": entity_type, "normalized_name": normalized_name}
                for entity_type, normalized_name in self.graph.entities
            ]
        raise AssertionError(f"unexpected read query: {query}")

    def execute_write(self, function, *args):
        self.execute_write_calls += 1
        return function(self.transaction, *args)


class _Driver:
    def __init__(self):
        self.graph = _GraphState()
        self.transaction = _Transaction(self.graph)
        self.sessions = []

    def session(self, **_kwargs):
        session = _Session(self.transaction, self.graph)
        self.sessions.append(session)
        return session


class _GraphState:
    def __init__(self):
        self.entities = {}
        self.assertions = {}
        self.has_assertion_edges = set()
        self.object_edges = set()
        self.aggregates = {}

    @staticmethod
    def _safe_old_keys(entities, base):
        entity_type, normalized_name = base
        return [
            key
            for key in entities
            if key[0] == entity_type
            and key != base
            and key[1].endswith(normalized_name)
            and key[1][: -len(normalized_name)] in {"临时", "作业"}
        ]

    def _ensure_entity(self, entity):
        key = (entity["entity_type"], entity["normalized_name"])
        self.entities.setdefault(
            key,
            {"name": entity["normalized_name"], "aliases": []},
        )
        return key

    def _add_alias(self, entity, alias):
        aliases = self.entities[entity]["aliases"]
        if alias not in aliases:
            aliases.append(alias)

    def _replace_assertion_edges(self, assertion_id, head, tail):
        self.has_assertion_edges = {
            edge for edge in self.has_assertion_edges if edge[1] != assertion_id
        }
        self.object_edges = {
            edge for edge in self.object_edges if edge[0] != assertion_id
        }
        self.has_assertion_edges.add((head, assertion_id))
        self.object_edges.add((assertion_id, tail))

    def remove_assertion(self, assertion_id):
        del self.assertions[assertion_id]
        self.has_assertion_edges = {
            edge for edge in self.has_assertion_edges if edge[1] != assertion_id
        }
        self.object_edges = {
            edge for edge in self.object_edges if edge[0] != assertion_id
        }

    def _move_head_edge(self, old, base, assertion_id):
        self.has_assertion_edges.discard((old, assertion_id))
        self.has_assertion_edges.add((base, assertion_id))
        self.assertions[assertion_id]["head"] = base

    def _move_tail_edge(self, old, base, assertion_id):
        self.object_edges.discard((assertion_id, old))
        self.object_edges.add((assertion_id, base))
        self.assertions[assertion_id]["tail"] = base

    def migrate(self, role, entities):
        for entity in entities:
            base = self._ensure_entity(entity)
            for old in self._safe_old_keys(list(self.entities), base):
                if role == "head":
                    assertion_ids = [
                        assertion_id
                        for edge, assertion_id in self.has_assertion_edges
                        if edge == old
                    ]
                    for assertion_id in assertion_ids:
                        self._move_head_edge(old, base, assertion_id)
                else:
                    assertion_ids = [
                        assertion_id
                        for assertion_id, edge in self.object_edges
                        if edge == old
                    ]
                    for assertion_id in assertion_ids:
                        self._move_tail_edge(old, base, assertion_id)
                self._add_alias(base, self.entities[old]["name"])

    def merge_old_aliases(self, entities):
        for entity in entities:
            base = self._ensure_entity(entity)
            for old in self._safe_old_keys(list(self.entities), base):
                for alias in self.entities[old]["aliases"] + [self.entities[old]["name"]]:
                    self._add_alias(base, alias)

    def upsert_assertions(self, items):
        for item in items:
            head = self._ensure_entity(item["head"])
            tail = self._ensure_entity(item["tail"])
            self.assertions[item["assertion_id"]] = {
                "head": head,
                "tail": tail,
                "relation": item["relation_type"],
                "metadata": item["metadata"],
            }
            self._replace_assertion_edges(item["assertion_id"], head, tail)

    def add_raw_aliases(self, items):
        for item in items:
            for side, raw_key in (("head", "raw_head_name"), ("tail", "raw_tail_name")):
                entity = self._ensure_entity(item[side])
                raw_name = item["metadata"][raw_key]
                self._add_alias(entity, raw_name)

    def delete_migrated_orphans(self, entities):
        connected = (
            {entity for entity, _ in self.has_assertion_edges}
            | {entity for _, entity in self.object_edges}
        )
        for entity in entities:
            base = (entity["entity_type"], entity["normalized_name"])
            for old in self._safe_old_keys(list(self.entities), base):
                if old not in connected:
                    del self.entities[old]

    def rebuild_aggregate(self, relation):
        heads = {
            assertion_id: entity
            for entity, assertion_id in self.has_assertion_edges
        }
        tails = {
            assertion_id: entity
            for assertion_id, entity in self.object_edges
        }
        for assertion_id, assertion in self.assertions.items():
            if assertion["relation"] == relation:
                self.aggregates[(heads[assertion_id], relation, tails[assertion_id])] = True


class Neo4jGraphTests(unittest.TestCase):
    def test_normalize_name(self):
        self.assertEqual(normalize_entity_name(" ＡBC  脚手架 "), "abc 脚手架")

    def test_containment_canonicalization(self):
        self.assertEqual(
            _canonical("作业脚手架", "设备", {("设备", "脚手架")}),
            ("脚手架", "containment"),
        )

    def test_containment_does_not_merge_suffix_or_specification(self):
        known = {("材料", "水泥"), ("设备", "用电")}
        self.assertEqual(_canonical("水泥浆", "材料", known)[0], "水泥浆")
        self.assertEqual(_canonical("高压用电", "设备", known)[0], "高压用电")

    def test_password_is_required(self):
        old = os.environ.pop("NEO4J_PASSWORD", None)
        try:
            with self.assertRaises(ValueError):
                Neo4jSettings.from_env()
        finally:
            if old is not None:
                os.environ["NEO4J_PASSWORD"] = old

    def test_canonical_has_no_legacy_unreachable_candidates_implementation(self):
        source = Path(__file__).resolve().parents[1] / "neo4j_graph.py"
        text = source.read_text(encoding="utf-8")
        function = text[text.index("def _canonical") : text.index("def _json_property")]
        self.assertEqual(function.count("candidates ="), 1)
        self.assertNotIn("return name, \"containment\" if name != raw_norm else \"exact\"\n\n    ", function)

    def test_stateful_fake_sync_covers_migration_idempotency_and_empty_run_cleanup(self):
        def source(run_id, triplets):
            return {
                "run": {"run_id": run_id, "schema_snapshot": {"version": 1}},
                "triplets": triplets,
                "evidence_by_triplet": {7: [{"chunk_index": 4, "text": "证据"}]},
            }

        def triplet(triplet_id, head, tail):
            return {
                "triplet_id": triplet_id,
                "head": head,
                "head_type": "设备",
                "tail": tail,
                "tail_type": "设备",
                "relation_name": "USES",
                "document_id": 9,
                "file_name": "安全方案.pdf",
                "source_llm_call_id": 12,
                "model_name": "model-x",
                "llm_metadata": {"prompt_version": "v3", "temperature": 0},
                "created_at": "2026-07-23T00:00:00+00:00",
            }

        class Store:
            def __init__(self):
                self.inputs = {}

            def load_graph_sync_input(self, run_id):
                return self.inputs[run_id]

        store = Store()
        store.inputs["run-old"] = source("run-old", [triplet(1, "临时用电", "脚手架")])
        store.inputs["run-new"] = source("run-new", [triplet(7, "用电", "脚手架")])
        schema = type("Schema", (), {"relation_type_names": {"USES"}})()
        driver = _Driver()
        syncer = Neo4jGraphSynchronizer(driver, store, schema)

        old_result = syncer.sync_run("run-old")
        result = syncer.sync_run("run-new")

        self.assertEqual(old_result.assertions_created, 1)
        self.assertEqual(result.assertions_created, 1)
        self.assertEqual(result.assertions_updated, 0)
        self.assertEqual(result.assertions_deleted, 0)
        self.assertEqual(result.aggregate_edges_total, 1)
        self.assertNotIn(("设备", "临时用电"), driver.graph.entities)
        self.assertIn("临时用电", driver.graph.entities[("设备", "用电")]["aliases"])
        self.assertEqual(driver.graph.assertions["run-old:1"]["head"], ("设备", "用电"))
        self.assertEqual(
            driver.graph.has_assertion_edges,
            {
                (("设备", "用电"), "run-old:1"),
                (("设备", "用电"), "run-new:7"),
            },
        )
        self.assertIn(
            ("run-old:1", ("设备", "脚手架")),
            driver.graph.object_edges,
        )

        store.inputs["run-new"] = source("run-new", [triplet(7, "用电", "安全帽")])
        repeat_result = syncer.sync_run("run-new")
        self.assertEqual(repeat_result.assertions_created, 0)
        self.assertEqual(repeat_result.assertions_updated, 1)
        self.assertEqual(len(driver.graph.assertions), 2)
        self.assertEqual(driver.graph.assertions["run-new:7"]["tail"], ("设备", "安全帽"))

        store.inputs["run-new"] = source("run-new", [])
        empty_result = syncer.sync_run("run-new")
        self.assertEqual(empty_result.assertions_deleted, 1)
        self.assertNotIn("run-new:7", driver.graph.assertions)
        self.assertIn("run-old:1", driver.graph.assertions)
        self.assertEqual(len(driver.graph.assertions), 1)
        self.assertEqual(empty_result.aggregate_edges_total, 1)

        self.assertEqual(len(driver.sessions), 8)
        self.assertEqual(sum(s.execute_write_calls for s in driver.sessions), 4)
        self.assertTrue(all(session.closed for session in driver.sessions))

        calls = driver.transaction.calls
        queries = "\n".join(query for query, _ in calls)
        self.assertIn("old_head:HAS_ASSERTION", queries)
        self.assertIn("old_tail:OBJECT", queries)
        self.assertIn("IN ['临时','作业']", queries)
        self.assertIn("coalesce(old.aliases,[])", queries)
        self.assertIn("AND NOT (old)--() DELETE old", queries)

        assertion_call = next(
            params
            for query, params in calls
            if "MERGE (a:RelationAssertion" in query
            and params["items"]
            and params["items"][0]["assertion_id"] == "run-new:7"
        )
        item = assertion_call["items"][0]
        self.assertEqual(item["head"]["normalized_name"], "用电")
        self.assertEqual(item["tail"]["normalized_name"], "脚手架")
        self.assertEqual(
            json.loads(item["metadata"]["prompt_metadata_json"])["prompt_version"], "v3"
        )
        self.assertEqual(
            json.loads(item["metadata"]["schema_snapshot_json"]), {"version": 1}
        )
        self.assertEqual(
            json.loads(item["metadata"]["evidence_json"])[0]["chunk_index"], 4
        )

    def test_stateful_fake_moves_tail_edges_and_preserves_historical_aliases(self):
        def source(run_id, triplets):
            return {
                "run": {"run_id": run_id},
                "triplets": triplets,
                "evidence_by_triplet": {},
            }

        def triplet(triplet_id, tail):
            return {
                "triplet_id": triplet_id,
                "head": "安全帽",
                "head_type": "设备",
                "tail": tail,
                "tail_type": "设备",
                "relation_name": "USES",
            }

        class Store:
            def __init__(self):
                self.inputs = {}

            def load_graph_sync_input(self, run_id):
                return self.inputs[run_id]

        store = Store()
        store.inputs["run-tail-old"] = source(
            "run-tail-old", [triplet(2, "作业脚手架")]
        )
        store.inputs["run-tail-new"] = source(
            "run-tail-new", [triplet(3, "脚手架")]
        )
        driver = _Driver()
        syncer = Neo4jGraphSynchronizer(
            driver,
            store,
            type("Schema", (), {"relation_type_names": {"USES"}})(),
        )

        syncer.sync_run("run-tail-old")
        driver.graph.entities[("设备", "作业脚手架")]["aliases"].append("临时作业脚手架")
        created = syncer.sync_run("run-tail-new")

        self.assertEqual(created.assertions_created, 1)
        self.assertNotIn(("设备", "作业脚手架"), driver.graph.entities)
        self.assertIn(
            ("run-tail-old:2", ("设备", "脚手架")),
            driver.graph.object_edges,
        )
        self.assertNotIn(
            ("run-tail-old:2", ("设备", "作业脚手架")),
            driver.graph.object_edges,
        )
        aliases = driver.graph.entities[("设备", "脚手架")]["aliases"]
        self.assertIn("作业脚手架", aliases)
        self.assertIn("临时作业脚手架", aliases)

        store.inputs["run-tail-new"] = source(
            "run-tail-new", [triplet(3, "防护栏")]
        )
        updated = syncer.sync_run("run-tail-new")
        self.assertEqual(updated.assertions_created, 0)
        self.assertEqual(updated.assertions_updated, 1)
        self.assertEqual(
            {
                edge
                for edge in driver.graph.object_edges
                if edge[0] == "run-tail-new:3"
            },
            {("run-tail-new:3", ("设备", "防护栏"))},
        )
        self.assertEqual(
            {
                edge
                for edge in driver.graph.has_assertion_edges
                if edge[1] == "run-tail-new:3"
            },
            {(("设备", "安全帽"), "run-tail-new:3")},
        )

        store.inputs["run-tail-new"] = source("run-tail-new", [])
        deleted = syncer.sync_run("run-tail-new")
        self.assertEqual(deleted.assertions_deleted, 1)
        self.assertNotIn("run-tail-new:3", driver.graph.assertions)
        self.assertFalse(
            any(
                assertion_id == "run-tail-new:3"
                for _, assertion_id in driver.graph.has_assertion_edges
            )
        )
        self.assertFalse(
            any(
                assertion_id == "run-tail-new:3"
                for assertion_id, _ in driver.graph.object_edges
            )
        )


if __name__ == "__main__":
    unittest.main()
