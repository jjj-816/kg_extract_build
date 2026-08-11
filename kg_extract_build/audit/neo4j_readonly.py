"""Read-only Neo4j adapter for bounded, provenance-preserving graph clues."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Mapping

from .bounded_graph import ReadOnlyGraph


@dataclass(frozen=True)
class Neo4jReadOnlySettings:
    uri: str
    user: str
    password: str
    database: str = "neo4j"

    @classmethod
    def from_env(cls) -> "Neo4jReadOnlySettings":
        password = os.getenv("NEO4J_PASSWORD", "").strip()
        if not password:
            raise ValueError("NEO4J_PASSWORD must be configured")
        return cls(
            os.getenv("NEO4J_URI", "bolt://localhost:7687").strip(),
            os.getenv("NEO4J_USER", "neo4j").strip(),
            password,
            os.getenv("NEO4J_DATABASE", "neo4j").strip() or "neo4j",
        )


class Neo4jReadOnlyGraph(ReadOnlyGraph):
    """Expose only confirmed assertion nodes; never writes or returns aggregates."""

    def __init__(self, driver, database: str = "neo4j"):
        self.driver = driver
        self.database = database

    @classmethod
    def from_env(cls) -> "Neo4jReadOnlyGraph":
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError("neo4j package is required for graph retrieval") from exc
        settings = Neo4jReadOnlySettings.from_env()
        return cls(GraphDatabase.driver(settings.uri, auth=(settings.user, settings.password)), settings.database)

    def query_clues(self, *, task_id: str, query: str, relationship_types: tuple[str, ...], max_hops: int) -> list[Mapping[str, Any]]:
        if not 1 <= max_hops <= 2:
            raise ValueError("max_hops must be 1 or 2")
        allowed = tuple(dict.fromkeys(str(item) for item in relationship_types if str(item).strip()))
        if not allowed:
            return []
        # One assertion hop is four physical graph edges; two assertion hops are eight.
        max_edges = 4 * max_hops
        cypher = (
            "MATCH p=(start:Entity)-[:HAS_ASSERTION|OBJECT*2.." + str(max_edges) + "]->(finish:Entity) "
            "WHERE NOT any(r IN relationships(p) WHERE coalesce(r.__kg_aggregate,false)) "
            "AND (toLower(coalesce(start.name,'')) CONTAINS toLower($query_text) "
            "OR toLower(coalesce(finish.name,'')) CONTAINS toLower($query_text)) "
            "WITH p, [n IN nodes(p) WHERE n:RelationAssertion] AS assertions "
            "UNWIND assertions AS a "
            "WITH assertions, a WHERE a.relation_type IN $relationship_types "
            "RETURN a.assertion_id AS clue_id, a.assertion_id AS assertion_id, "
            "a.relation_type AS relationship_type, "
            "CASE WHEN size(assertions) = 0 THEN 0 ELSE size(assertions) END AS hops, "
            "a.document_id AS source_document_id, "
            "coalesce(a.evidence_sentence,a.raw_text,'') AS evidence_sentence, "
            "coalesce(a.summary,'') AS summary, true AS confirmed_case"
        )
        with self.driver.session(database=self.database) as session:
            return [record.data() if hasattr(record, "data") else dict(record) for record in session.run(
                cypher, query_text=query or "", relationship_types=list(allowed), task_id=task_id,
            )]

    def close(self) -> None:
        self.driver.close()
