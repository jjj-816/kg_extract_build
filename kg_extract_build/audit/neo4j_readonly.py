"""Read-only Neo4j adapter for bounded, provenance-preserving graph clues."""

from __future__ import annotations

from dataclasses import dataclass
import json
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
        match_condition = (
            "(toLower(coalesce(matched.name,'')) CONTAINS toLower($query_text) "
            "OR any(alias IN coalesce(matched.aliases,[]) WHERE toLower(alias) CONTAINS toLower($query_text))) "
        )
        fields = (
            "candidate.assertion_id AS clue_id, candidate.assertion_id AS assertion_id, "
            "candidate.relation_type AS relationship_type, hops, match_kind, matched.name AS matched_entity, "
            "candidate.document_id AS source_document_id, coalesce(candidate.evidence_sentence,candidate.raw_text,'') AS evidence_sentence, "
            "candidate.evidence_json AS evidence_json, coalesce(candidate.summary,'') AS summary, true AS confirmed_case"
        )
        direct = (
            "MATCH (matched:Entity)-[head:HAS_ASSERTION]-(direct:RelationAssertion) "
            "WHERE " + match_condition + "AND direct.relation_type IN $relationship_types "
            "AND NOT coalesce(head.__kg_aggregate,false) "
            "WITH matched, direct AS candidate, 1 AS hops, 'direct' AS match_kind "
            "RETURN DISTINCT " + fields
        )
        if max_hops == 1:
            cypher = direct
        else:
            expanded = (
                "MATCH (matched:Entity)-[head:HAS_ASSERTION]-(first:RelationAssertion)-[tail:OBJECT]-(neighbor:Entity) "
                "MATCH (neighbor)-[next_head:HAS_ASSERTION]-(expanded:RelationAssertion) "
                "WHERE " + match_condition + "AND expanded.relation_type IN $relationship_types "
                "AND expanded.assertion_id <> first.assertion_id "
                "AND NOT coalesce(head.__kg_aggregate,false) AND NOT coalesce(tail.__kg_aggregate,false) "
                "AND NOT coalesce(next_head.__kg_aggregate,false) "
                "WITH matched, expanded AS candidate, 2 AS hops, 'expanded' AS match_kind "
                "RETURN DISTINCT " + fields
            )
            cypher = direct + " UNION " + expanded
        with self.driver.session(database=self.database) as session:
            rows = [record.data() if hasattr(record, "data") else dict(record) for record in session.run(
                cypher, query_text=query or "", relationship_types=list(allowed), task_id=task_id,
            )]
        for row in rows:
            if not str(row.get("evidence_sentence") or "").strip():
                row["evidence_sentence"] = _legacy_evidence_sentence(row.get("evidence_json"))
        return rows

    def close(self) -> None:
        self.driver.close()


def _legacy_evidence_sentence(value: Any) -> str:
    """Read the first usable sentence from legacy RelationAssertion evidence_json."""
    if not value:
        return ""
    try:
        evidence = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return ""
    if not isinstance(evidence, list):
        return ""
    for item in evidence:
        if isinstance(item, Mapping):
            sentence = str(item.get("sentence") or "").strip()
            if sentence:
                return sentence
    return ""
