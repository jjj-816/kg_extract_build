from pathlib import Path

from kg_extract_build.dashboard_neo4j import (
    ASSERTION_COLOR,
    ENTITY_COLOR,
    aggregate_edge_query,
    eligible_runs,
    graph_records_to_agraph,
    neo4j_sync_enabled,
    provenance_graph_query,
)


def test_eligible_runs_excludes_failed_and_pending_deletion():
    rows = [
        {"run_id": "ok", "status": "completed", "deletion_state": "active"},
        {"run_id": "bad", "status": "failed", "deletion_state": "active"},
        {
            "run_id": "gone",
            "status": "completed",
            "deletion_state": "vectors_deleted_sql_pending",
        },
    ]
    assert [row["run_id"] for row in eligible_runs(rows)] == ["ok"]


def test_sync_requires_mysql(monkeypatch):
    monkeypatch.setenv("KG_MYSQL_ENABLED", "0")
    assert neo4j_sync_enabled()[0] is False


def test_aggregate_edge_query_filters_neo4j_aggregate_edges():
    query, params = aggregate_edge_query("设备", "USES", "脚手架", 42)

    assert "r.__kg_aggregate = true" in query
    assert "type(r) = $relation_type" in query
    assert "toLower(h.name) CONTAINS toLower($entity_name)" in query
    assert params == {
        "limit": 42,
        "entity_type": "设备",
        "relation_type": "USES",
        "entity_name": "脚手架",
    }


def test_provenance_query_uses_assertion_nodes_and_relation_filter():
    query, params = provenance_graph_query("", "USES", "", 20)

    assert "[:HAS_ASSERTION {role:'head'}]" in query
    assert "[:OBJECT {role:'tail'}]" in query
    assert "a.relation_type = $relation_type" in query
    assert params == {"relation_type": "USES", "limit": 20}


def test_aggregate_graph_keeps_same_name_different_type_as_distinct_nodes():
    nodes, edges, details = graph_records_to_agraph(
        [
            {
                "head_name": "作业",
                "head_type": "活动",
                "head_aliases": [],
                "relation_type": "USES",
                "tail_name": "脚手架",
                "tail_type": "设备",
                "tail_aliases": [],
                "assertion_count": 1,
                "document_count": 1,
            },
            {
                "head_name": "作业",
                "head_type": "文档",
                "head_aliases": [],
                "relation_type": "REFERS_TO",
                "tail_name": "脚手架",
                "tail_type": "设备",
                "tail_aliases": [],
                "assertion_count": 1,
                "document_count": 1,
            },
        ],
        "aggregate",
    )

    assert len(nodes) == 3
    assert len(edges) == 2
    assert {node["color"] for node in nodes} == {ENTITY_COLOR}
    assert "entity:活动:作业" in details
    assert "entity:文档:作业" in details


def test_provenance_graph_creates_assertion_node_and_metadata_detail():
    nodes, edges, details = graph_records_to_agraph(
        [
            {
                "head_name": "电工",
                "head_type": "人员",
                "head_aliases": [],
                "assertion_id": "run-1:7",
                "relation_type": "RESPONSIBLE_FOR",
                "run_id": "run-1",
                "triplet_id": 7,
                "document_id": 3,
                "file_name": "方案.pdf",
                "model_name": "model-x",
                "prompt_version": "v2",
                "prompt_metadata_json": "{\"temperature\":0}",
                "schema_snapshot_json": "{\"version\":1}",
                "evidence_json": "[]",
                "extracted_at": "2026-07-24T00:00:00+00:00",
                "tail_name": "高压电工",
                "tail_type": "人员",
                "tail_aliases": [],
            }
        ],
        "provenance",
    )

    assertion = next(node for node in nodes if node["id"] == "assertion:run-1:7")
    assert assertion["color"] == ASSERTION_COLOR
    assert len(edges) == 2
    assert details["assertion:run-1:7"]["文件名"] == "方案.pdf"
    assert details["assertion:run-1:7"]["证据"] == "[]"


def test_interactive_graph_uses_pixel_width():
    source = (Path(__file__).resolve().parents[1] / "dashboard_neo4j.py").read_text(
        encoding="utf-8"
    )

    assert 'width=int(width)' in source
    assert 'width="100%"' not in source
