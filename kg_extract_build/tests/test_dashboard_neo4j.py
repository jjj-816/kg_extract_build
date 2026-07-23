from kg_extract_build.dashboard_neo4j import eligible_runs, neo4j_sync_enabled


def test_eligible_runs_excludes_failed_and_pending_deletion():
    rows = [{"run_id":"ok","status":"completed","deletion_state":"active"}, {"run_id":"bad","status":"failed","deletion_state":"active"}, {"run_id":"gone","status":"completed","deletion_state":"vectors_deleted_sql_pending"}]
    assert [row["run_id"] for row in eligible_runs(rows)] == ["ok"]


def test_sync_requires_mysql(monkeypatch):
    monkeypatch.setenv("KG_MYSQL_ENABLED", "0")
    assert neo4j_sync_enabled()[0] is False
