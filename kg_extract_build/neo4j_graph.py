"""Provenance-preserving synchronization of final triplets into Neo4j."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone


RELATION_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
CONTAINMENT_PREFIXES = frozenset({"临时", "作业"})


@dataclass(frozen=True)
class Neo4jSettings:
    uri: str
    user: str
    password: str
    database: str

    @classmethod
    def from_env(cls):
        password = os.getenv("NEO4J_PASSWORD", "").strip()
        if not password:
            raise ValueError("NEO4J_PASSWORD must be configured in .env")
        return cls(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            os.getenv("NEO4J_USER", "neo4j"),
            password,
            os.getenv("NEO4J_DATABASE", "neo4j"),
        )


def normalize_entity_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = " ".join(text.split())
    return "".join(ch.lower() if ch.isascii() and ch.isalpha() else ch for ch in text)


def _canonical(raw: str, entity_type: str, known: set[tuple[str, str]]):
    """Return a safe canonical entity name and the method used.

    Only explicitly approved prefix qualifiers can collapse into an existing
    shorter entity.  This deliberately leaves material suffixes, dimensions,
    pressure grades, and other specifications as separate entities.
    """
    raw_norm = normalize_entity_name(raw)
    candidates = [
        name
        for kind, name in known
        if kind == entity_type
        and name != raw_norm
        and raw_norm.endswith(name)
        and raw_norm[: -len(name)] in CONTAINMENT_PREFIXES
    ]
    name = max(candidates, key=len) if candidates else raw_norm
    return name, "containment" if name != raw_norm else "exact"


def _json_property(value):
    """Convert structured source metadata to a Neo4j-safe JSON string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


@dataclass
class SyncRunResult:
    run_id: str
    assertions_created: int
    assertions_updated: int
    assertions_deleted: int
    aggregate_edges_total: int


class Neo4jGraphSynchronizer:
    def __init__(self, driver, store, schema, database=None):
        self.driver = driver
        self.store = store
        self.schema = schema
        self.database = database

    @classmethod
    def from_env(cls, store, schema):
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError("Install the neo4j package before synchronizing") from exc
        config = Neo4jSettings.from_env()
        return cls(
            GraphDatabase.driver(config.uri, auth=(config.user, config.password)),
            store,
            schema,
            config.database,
        )

    def check_connection(self):
        self.driver.verify_connectivity()

    def sync_run(self, run_id: str) -> SyncRunResult:
        source = self.store.load_graph_sync_input(run_id)
        run = source.get("run") or {}
        if not run:
            raise ValueError(f"run not found: {run_id}")

        evidence = source.get("evidence_by_triplet", {})
        triplets = source.get("triplets", [])
        known = {
            (str(triplet.get(f"{side}_type")), normalize_entity_name(triplet.get(side)))
            for triplet in triplets
            for side in ("head", "tail")
        }
        with self.driver.session(database=self.database) as session:
            known |= {
                (row["entity_type"], row["normalized_name"])
                for row in session.run(
                    "MATCH (e:Entity) "
                    "RETURN e.entity_type AS entity_type,"
                    "e.normalized_name AS normalized_name"
                )
            }

        items = []
        for triplet in triplets:
            if not triplet.get("is_valid", True):
                continue
            relation = triplet.get("relation_name") or triplet.get("relation")
            if relation not in self.schema.relation_type_names or not RELATION_RE.fullmatch(relation):
                raise ValueError(f"unknown schema relation: {relation}")

            head_name, head_method = _canonical(
                triplet["head"], triplet["head_type"], known
            )
            tail_name, tail_method = _canonical(
                triplet["tail"], triplet["tail_type"], known
            )
            llm_metadata = triplet.get("llm_metadata") or {}
            if isinstance(llm_metadata, str):
                try:
                    llm_metadata = json.loads(llm_metadata)
                except json.JSONDecodeError:
                    llm_metadata = {"raw": llm_metadata}
            if not isinstance(llm_metadata, dict):
                llm_metadata = {"raw": llm_metadata}

            schema_snapshot = triplet.get("schema_snapshot")
            if schema_snapshot is None:
                schema_snapshot = run.get("schema_snapshot")
            items.append(
                {
                    "assertion_id": f"{run_id}:{triplet['triplet_id']}",
                    "relation_type": relation,
                    "head": {
                        "entity_type": triplet["head_type"],
                        "normalized_name": head_name,
                    },
                    "tail": {
                        "entity_type": triplet["tail_type"],
                        "normalized_name": tail_name,
                    },
                    "metadata": {
                        "run_id": run_id,
                        "triplet_id": triplet["triplet_id"],
                        "document_id": triplet.get("document_id"),
                        "file_name": triplet.get("file_name"),
                        "source_llm_call_id": triplet.get("source_llm_call_id"),
                        "model_name": triplet.get("model_name"),
                        "prompt_version": llm_metadata.get("prompt_version"),
                        "prompt_metadata_json": _json_property(llm_metadata),
                        "schema_snapshot_json": _json_property(schema_snapshot),
                        "raw_head_name": triplet["head"],
                        "raw_tail_name": triplet["tail"],
                        "head_canonicalization_method": head_method,
                        "tail_canonicalization_method": tail_method,
                        "evidence_json": _json_property(
                            evidence.get(triplet["triplet_id"], [])
                        ),
                        "extracted_at": str(
                            triplet.get("created_at") or datetime.now(timezone.utc)
                        ),
                        "synced_at": str(datetime.now(timezone.utc)),
                    },
                }
            )

        with self.driver.session(database=self.database) as session:
            stats = session.execute_write(
                self._sync_tx,
                run_id,
                items,
                sorted(self.schema.relation_type_names),
            )
        return SyncRunResult(run_id, **stats)

    def _sync_tx(self, tx, run_id, items, relation_types):
        tx.run(
            "CREATE CONSTRAINT entity_identity IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE (e.entity_type, e.normalized_name) IS UNIQUE"
        )
        tx.run(
            "CREATE CONSTRAINT assertion_identity IF NOT EXISTS "
            "FOR (a:RelationAssertion) REQUIRE a.assertion_id IS UNIQUE"
        )
        assertion_ids = [item["assertion_id"] for item in items]
        existing = tx.run(
            "MATCH (a:RelationAssertion) WHERE a.assertion_id IN $ids "
            "RETURN count(a) AS count",
            ids=assertion_ids,
        ).single()["count"]
        deleted = tx.run(
            "MATCH (a:RelationAssertion {run_id:$run_id}) "
            "WHERE NOT a.assertion_id IN $ids "
            "WITH collect(a) AS rows "
            "FOREACH (a IN rows | DETACH DELETE a) "
            "RETURN size(rows) AS count",
            run_id=run_id,
            ids=assertion_ids,
        ).single()["count"]
        canonical_entities = [
            {
                "entity_type": item[side]["entity_type"],
                "normalized_name": item[side]["normalized_name"],
            }
            for item in items
            for side in ("head", "tail")
        ]
        safe_where = (
            "old.normalized_name ENDS WITH item.normalized_name AND "
            "left(old.normalized_name, size(old.normalized_name)-"
            "size(item.normalized_name)) IN ['临时','作业']"
        )
        tx.run(
            f"UNWIND $entities AS item "
            f"MERGE (base:Entity {{entity_type:item.entity_type, "
            f"normalized_name:item.normalized_name}}) "
            f"SET base.name=item.normalized_name "
            f"WITH base,item MATCH (old:Entity {{entity_type:item.entity_type}}) "
            f"WHERE {safe_where} AND old <> base "
            f"MATCH (old)-[h:HAS_ASSERTION {{role:'head'}}]->(a) DELETE h "
            f"MERGE (base)-[:HAS_ASSERTION {{role:'head'}}]->(a) "
            f"SET base.aliases=CASE WHEN old.name IN coalesce(base.aliases,[]) "
            f"THEN coalesce(base.aliases,[]) "
            f"ELSE coalesce(base.aliases,[])+old.name END",
            entities=canonical_entities,
        )
        tx.run(
            f"UNWIND $entities AS item "
            f"MATCH (base:Entity {{entity_type:item.entity_type, "
            f"normalized_name:item.normalized_name}}) "
            f"MATCH (old:Entity {{entity_type:item.entity_type}}) "
            f"WHERE {safe_where} AND old <> base "
            f"MATCH (a)-[o:OBJECT {{role:'tail'}}]->(old) DELETE o "
            f"MERGE (a)-[:OBJECT {{role:'tail'}}]->(base) "
            f"SET base.aliases=CASE WHEN old.name IN coalesce(base.aliases,[]) "
            f"THEN coalesce(base.aliases,[]) "
            f"ELSE coalesce(base.aliases,[])+old.name END",
            entities=canonical_entities,
        )
        tx.run(
            f"UNWIND $entities AS item "
            f"MATCH (base:Entity {{entity_type:item.entity_type, "
            f"normalized_name:item.normalized_name}}) "
            f"MATCH (old:Entity {{entity_type:item.entity_type}}) "
            f"WHERE {safe_where} AND old <> base "
            f"WITH base, old, coalesce(base.aliases,[]) + "
            f"coalesce(old.aliases,[]) + [old.name] AS aliases "
            f"UNWIND aliases AS alias WITH base, collect(DISTINCT alias) AS aliases "
            f"SET base.aliases=aliases",
            entities=canonical_entities,
        )
        tx.run(
            "UNWIND $items AS item "
            "MERGE (h:Entity {entity_type:item.head.entity_type, "
            "normalized_name:item.head.normalized_name}) "
            "SET h.name=item.head.normalized_name "
            "MERGE (t:Entity {entity_type:item.tail.entity_type, "
            "normalized_name:item.tail.normalized_name}) "
            "SET t.name=item.tail.normalized_name "
            "MERGE (a:RelationAssertion {assertion_id:item.assertion_id}) "
            "OPTIONAL MATCH ()-[old_head:HAS_ASSERTION]->(a) DELETE old_head "
            "WITH item,a,h,t OPTIONAL MATCH (a)-[old_tail:OBJECT]->() DELETE old_tail "
            "WITH item,a,h,t SET a += item.metadata, a.relation_type=item.relation_type "
            "MERGE (h)-[:HAS_ASSERTION {role:'head'}]->(a) "
            "MERGE (a)-[:OBJECT {role:'tail'}]->(t)",
            items=items,
        )
        tx.run(
            "UNWIND $items AS item "
            "MATCH (h:Entity {entity_type:item.head.entity_type, "
            "normalized_name:item.head.normalized_name}) "
            "MATCH (t:Entity {entity_type:item.tail.entity_type, "
            "normalized_name:item.tail.normalized_name}) "
            "SET h.aliases=CASE WHEN item.metadata.raw_head_name "
            "IN coalesce(h.aliases,[]) THEN coalesce(h.aliases,[]) "
            "ELSE coalesce(h.aliases,[])+item.metadata.raw_head_name END, "
            "t.aliases=CASE WHEN item.metadata.raw_tail_name "
            "IN coalesce(t.aliases,[]) THEN coalesce(t.aliases,[]) "
            "ELSE coalesce(t.aliases,[])+item.metadata.raw_tail_name END",
            items=items,
        )
        tx.run("MATCH ()-[r]->() WHERE r.__kg_aggregate = true DELETE r")
        tx.run(
            f"UNWIND $entities AS item "
            f"MATCH (old:Entity {{entity_type:item.entity_type}}) "
            f"WHERE {safe_where} "
            f"AND NOT (old)--() "
            f"DELETE old",
            entities=canonical_entities,
        )
        marker = chr(96)
        for relation in relation_types:
            if not RELATION_RE.fullmatch(relation):
                continue
            tx.run(
                f"MATCH (h:Entity)-[:HAS_ASSERTION {{role:'head'}}]"
                f"->(a:RelationAssertion)-[:OBJECT {{role:'tail'}}]->(t:Entity) "
                f"WHERE a.relation_type=$relation "
                f"WITH h,t,count(a) AS assertions,count(DISTINCT a.document_id) "
                f"AS documents,max(a.extracted_at) AS last_seen "
                f"MERGE (h)-[r:{marker}{relation}{marker}]->(t) "
                f"SET r.__kg_aggregate=true,r.assertion_count=assertions,"
                f"r.document_count=documents,r.last_seen_at=last_seen",
                relation=relation,
            )
        aggregate_edges_total = tx.run(
            "MATCH ()-[r]->() WHERE r.__kg_aggregate=true RETURN count(r) AS count"
        ).single()["count"]
        return {
            "assertions_created": len(items) - existing,
            "assertions_updated": existing,
            "assertions_deleted": deleted,
            "aggregate_edges_total": aggregate_edges_total,
        }
