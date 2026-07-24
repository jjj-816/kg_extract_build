import os

import streamlit as st

from .neo4j_graph import Neo4jGraphSynchronizer, Neo4jSettings
from .persistence import build_experiment_store
from .schema import KGSchema
from .settings import resolve_schema_path


def neo4j_sync_enabled():
    enabled = os.getenv("KG_MYSQL_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return (
        enabled,
        "" if enabled else "请先启用 KG_MYSQL_ENABLED=1；图谱同步只读取 MySQL 中可追溯的最终三元组。",
    )


def eligible_runs(rows):
    return [
        row
        for row in rows
        if row.get("status") == "completed"
        and row.get("deletion_state", "active") == "active"
    ]


def aggregate_edge_query(entity_type="", relation_type="", entity_name="", limit=100):
    filters = ["r.__kg_aggregate = true"]
    params = {"limit": int(limit)}
    if entity_type:
        filters.append("(h.entity_type = $entity_type OR t.entity_type = $entity_type)")
        params["entity_type"] = entity_type
    if relation_type:
        filters.append("type(r) = $relation_type")
        params["relation_type"] = relation_type
    if entity_name:
        filters.append(
            "(toLower(h.name) CONTAINS toLower($entity_name) "
            "OR toLower(t.name) CONTAINS toLower($entity_name))"
        )
        params["entity_name"] = entity_name.strip()
    return (
        "MATCH (h:Entity)-[r]->(t:Entity) "
        f"WHERE {' AND '.join(filters)} "
        "RETURN h.name AS head_name, h.entity_type AS head_type, "
        "type(r) AS relation_type, t.name AS tail_name, t.entity_type AS tail_type, "
        "r.assertion_count AS assertion_count, r.document_count AS document_count, "
        "r.last_seen_at AS last_seen_at "
        "ORDER BY relation_type, head_name, tail_name LIMIT $limit",
        params,
    )


def _dot_escape(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def aggregate_edges_dot(rows):
    node_ids = {}

    def node_id(entity_type, name):
        key = (entity_type or "", name or "")
        if key not in node_ids:
            node_ids[key] = f"n{len(node_ids)}"
        return node_ids[key]

    lines = [
        "digraph Neo4jKG {",
        'graph [rankdir="LR", bgcolor="transparent"];',
        'node [shape="box", style="rounded,filled", fillcolor="#EFF6FF", color="#93C5FD", fontname="Microsoft YaHei"];',
        'edge [color="#64748B", fontname="Microsoft YaHei"];',
    ]
    for row in rows:
        head_id = node_id(row["head_type"], row["head_name"])
        tail_id = node_id(row["tail_type"], row["tail_name"])
        head_label = _dot_escape(f"{row['head_name']}\\n[{row['head_type']}]")
        tail_label = _dot_escape(f"{row['tail_name']}\\n[{row['tail_type']}]")
        relation = _dot_escape(row["relation_type"])
        lines.append(f'{head_id} [label="{head_label}"];')
        lines.append(f'{tail_id} [label="{tail_label}"];')
        lines.append(f'{head_id} -> {tail_id} [label="{relation}"];')
    lines.append("}")
    return "\n".join(lines)


def load_aggregate_edges(entity_type="", relation_type="", entity_name="", limit=100):
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("请安装 neo4j Python 驱动后再查看图谱") from exc
    config = Neo4jSettings.from_env()
    query, params = aggregate_edge_query(
        entity_type,
        relation_type,
        entity_name,
        limit,
    )
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    try:
        with driver.session(database=config.database) as session:
            return [dict(record) for record in session.run(query, **params)]
    finally:
        driver.close()


def render_neo4j_view_panel():
    st.subheader("从 Neo4j 查看图谱")
    st.caption("仅在点击查询后读取 Neo4j；建议先用实体名称或类型缩小到局部邻域。")
    with st.form("neo4j_graph_query"):
        entity_name = st.text_input("实体名称包含", placeholder="例如：脚手架")
        entity_type = st.text_input("实体类型", placeholder="例如：设备")
        relation_type = st.text_input("关系类型", placeholder="例如：USES")
        limit = st.slider("最多显示关系数", min_value=1, max_value=300, value=100)
        submitted = st.form_submit_button("查询 Neo4j 图谱", type="primary")
    if not submitted:
        return
    try:
        rows = load_aggregate_edges(entity_type, relation_type, entity_name, limit)
    except Exception as exc:
        st.error(f"无法查询 Neo4j 图谱：{exc}")
        return
    if not rows:
        st.info("没有匹配的 Neo4j 聚合关系。")
        return
    st.caption(f"已加载 {len(rows)} 条聚合关系。")
    st.graphviz_chart(aggregate_edges_dot(rows), use_container_width=True)
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_neo4j_sync_panel():
    st.subheader("同步到 Neo4j")
    enabled, reason = neo4j_sync_enabled()
    if not enabled:
        st.info(reason)
        return
    try:
        store = build_experiment_store()
        runs = eligible_runs(store.list_experiment_runs(200))
    except Exception as exc:
        st.error(f"无法读取 MySQL 实验记录：{exc}")
        return
    if not runs:
        st.info("没有可同步的已完成运行批次。")
        return
    labels = {
        row["run_id"]: f"{row.get('run_name', row['run_id'])} · {row['run_id']}"
        for row in runs
    }
    run_ids = st.multiselect(
        "选择要同步的运行批次",
        list(labels),
        format_func=labels.get,
    )
    if st.button("同步至 Neo4j", disabled=not run_ids, type="primary"):
        syncer = None
        try:
            syncer = Neo4jGraphSynchronizer.from_env(
                store,
                KGSchema(resolve_schema_path()),
            )
            syncer.check_connection()
            results = []
            for run_id in run_ids:
                try:
                    results.append(
                        {
                            **syncer.sync_run(run_id).__dict__,
                            "status": "success",
                            "error": "",
                        }
                    )
                except Exception as exc:
                    results.append(
                        {"run_id": run_id, "status": "failed", "error": str(exc)}
                    )
            st.success("Neo4j 同步处理完成")
            st.dataframe(results, use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"Neo4j 同步失败：{exc}")
        finally:
            store.close()
            if syncer is not None:
                syncer.driver.close()
