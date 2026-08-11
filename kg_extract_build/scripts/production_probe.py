"""Read-only production service probe; never prints credentials."""

from __future__ import annotations

import urllib.request

import kg_extract_build.audit.settings  # loads repository .env
from kg_extract_build.audit.neo4j_readonly import Neo4jReadOnlyGraph
from kg_extract_build.persistence import MySQLExperimentStore


def main() -> int:
    store = MySQLExperimentStore.from_env()
    try:
        releases = store._read("SELECT release_id, status FROM kg_normative_index_release WHERE status='published'")
        versions = store._read("SELECT version_id, family_id, status, metadata_confirmed FROM kg_normative_version")
        print(f"published_releases={releases}")
        print(f"normative_versions={versions}")
    finally:
        store.close()
    try:
        graph = Neo4jReadOnlyGraph.from_env()
        try:
            clues = graph.query_clues(
                task_id="APPD-004", query="pump",
                relationship_types=("USES", "REQUIRES", "CONTROLS"), max_hops=2,
            )
            print(f"neo4j_readonly_ok=true clue_count={len(clues)}")
        finally:
            graph.close()
    except Exception as exc:
        print(f"neo4j_readonly_degraded={type(exc).__name__}:{exc}")
    try:
        with urllib.request.urlopen("http://127.0.0.1:5001/audit_jsa", timeout=5) as response:
            print(f"jsa_http_status={response.status}")
    except Exception as exc:
        print(f"jsa_probe_error={type(exc).__name__}:{exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
