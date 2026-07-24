from kg_extract_build.dashboard_neo4j import (
    aggregate_edge_query,
    aggregate_edges_dot,
    eligible_runs,
    neo4j_sync_enabled,
)


def test_eligible_runs_excludes_failed_and_pending_deletion():
    rows = [{"run_id":"ok","status":"completed","deletion_state":"active"}, {"run_id":"bad","status":"failed","deletion_state":"active"}, {"run_id":"gone","status":"completed","deletion_state":"vectors_deleted_sql_pending"}]
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


def test_aggregate_edges_dot_keeps_same_name_different_type_as_distinct_nodes():
    dot = aggregate_edges_dot(
        [
            {
                "head_name": "作业",
                "head_type": "活动",
                "relation_type": "USES",
                "tail_name": "脚手架",
                "tail_type": "设备",
            },
            {
                "head_name": "作业",
                "head_type": "文档",
                "relation_type": "REFERS_TO",
                "tail_name": "脚手架",
                "tail_type": "设备",
            },
        ]
    )

    assert 'n0 [label="作业\\\\n[活动]"];' in dot
    assert 'n2 [label="作业\\\\n[文档]"];' in dot
