import os

import streamlit as st

from .neo4j_graph import Neo4jGraphSynchronizer, Neo4jSettings
from .persistence import build_experiment_store
from .schema import KGSchema
from .settings import resolve_schema_path


ENTITY_COLOR = "#C98F82"
ASSERTION_COLOR = "#13D8B5"


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


def _query_filters(entity_type, relation_type, entity_name, relation_expression):
    filters = []
    params = {}
    if entity_type:
        filters.append("(h.entity_type = $entity_type OR t.entity_type = $entity_type)")
        params["entity_type"] = entity_type.strip()
    if relation_type:
        filters.append(f"{relation_expression} = $relation_type")
        params["relation_type"] = relation_type.strip()
    if entity_name:
        filters.append(
            "(toLower(h.name) CONTAINS toLower($entity_name) "
            "OR toLower(t.name) CONTAINS toLower($entity_name))"
        )
        params["entity_name"] = entity_name.strip()
    return filters, params


def aggregate_edge_query(entity_type="", relation_type="", entity_name="", limit=100):
    filters, params = _query_filters(
        entity_type,
        relation_type,
        entity_name,
        "type(r)",
    )
    filters.insert(0, "r.__kg_aggregate = true")
    params["limit"] = int(limit)
    return (
        "MATCH (h:Entity)-[r]->(t:Entity) "
        f"WHERE {' AND '.join(filters)} "
        "RETURN h.name AS head_name, h.entity_type AS head_type, h.aliases AS head_aliases, "
        "type(r) AS relation_type, t.name AS tail_name, t.entity_type AS tail_type, "
        "t.aliases AS tail_aliases, r.assertion_count AS assertion_count, "
        "r.document_count AS document_count, r.last_seen_at AS last_seen_at "
        "ORDER BY relation_type, head_name, tail_name LIMIT $limit",
        params,
    )


def provenance_graph_query(entity_type="", relation_type="", entity_name="", limit=100):
    filters, params = _query_filters(
        entity_type,
        relation_type,
        entity_name,
        "a.relation_type",
    )
    params["limit"] = int(limit)
    where = f"WHERE {' AND '.join(filters)} " if filters else ""
    return (
        "MATCH (h:Entity)-[:HAS_ASSERTION {role:'head'}]->(a:RelationAssertion)"
        "-[:OBJECT {role:'tail'}]->(t:Entity) "
        f"{where}"
        "RETURN h.name AS head_name, h.entity_type AS head_type, h.aliases AS head_aliases, "
        "a.assertion_id AS assertion_id, a.relation_type AS relation_type, "
        "a.run_id AS run_id, a.triplet_id AS triplet_id, a.document_id AS document_id, "
        "a.file_name AS file_name, a.model_name AS model_name, "
        "a.prompt_version AS prompt_version, a.prompt_metadata_json AS prompt_metadata_json, "
        "a.schema_snapshot_json AS schema_snapshot_json, a.evidence_json AS evidence_json, "
        "a.extracted_at AS extracted_at, "
        "t.name AS tail_name, t.entity_type AS tail_type, t.aliases AS tail_aliases "
        "ORDER BY relation_type, head_name, tail_name LIMIT $limit",
        params,
    )


def _entity_id(entity_type, name):
    return f"entity:{entity_type or ''}:{name or ''}"


def _entity_node(entity_type, name, aliases):
    return {
        "id": _entity_id(entity_type, name),
        "label": str(name or ""),
        "title": f"实体类型：{entity_type or ''}",
        "shape": "dot",
        "size": 28,
        "color": ENTITY_COLOR,
        "detail": {
            "节点类型": "Entity",
            "实体名称": name,
            "实体类型": entity_type,
            "别名": aliases or [],
        },
    }


def graph_records_to_agraph(rows, mode):
    nodes = {}
    edges = []

    def add_entity(entity_type, name, aliases):
        node = _entity_node(entity_type, name, aliases)
        nodes.setdefault(node["id"], node)
        return node["id"]

    for row in rows:
        head_id = add_entity(
            row["head_type"],
            row["head_name"],
            row.get("head_aliases"),
        )
        tail_id = add_entity(
            row["tail_type"],
            row["tail_name"],
            row.get("tail_aliases"),
        )
        if mode == "aggregate":
            edges.append(
                {
                    "source": head_id,
                    "target": tail_id,
                    "label": row["relation_type"],
                    "title": (
                        f"断言数：{row.get('assertion_count') or 0}；"
                        f"文档数：{row.get('document_count') or 0}"
                    ),
                    "arrows": "to",
                }
            )
            continue

        assertion_id = f"assertion:{row['assertion_id']}"
        nodes.setdefault(
            assertion_id,
            {
                "id": assertion_id,
                "label": row["relation_type"],
                "title": f"关系断言：{row['assertion_id']}",
                "shape": "dot",
                "size": 22,
                "color": ASSERTION_COLOR,
                "detail": {
                    "节点类型": "RelationAssertion",
                    "断言 ID": row["assertion_id"],
                    "关系类型": row["relation_type"],
                    "运行 ID": row.get("run_id"),
                    "三元组 ID": row.get("triplet_id"),
                    "文档 ID": row.get("document_id"),
                    "文件名": row.get("file_name"),
                    "模型": row.get("model_name"),
                    "提示词版本": row.get("prompt_version"),
                    "提示词元数据": row.get("prompt_metadata_json"),
                    "Schema 快照": row.get("schema_snapshot_json"),
                    "证据": row.get("evidence_json"),
                    "抽取时间": row.get("extracted_at"),
                },
            },
        )
        edges.extend(
            [
                {
                    "source": head_id,
                    "target": assertion_id,
                    "label": "HAS_ASSERTION",
                    "arrows": "to",
                },
                {
                    "source": assertion_id,
                    "target": tail_id,
                    "label": "OBJECT",
                    "arrows": "to",
                },
            ]
        )

    details = {node_id: node.pop("detail") for node_id, node in nodes.items()}
    return list(nodes.values()), edges, details


def load_neo4j_graph(mode, entity_type="", relation_type="", entity_name="", limit=100):
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("请安装 neo4j Python 驱动后再查看图谱") from exc
    config = Neo4jSettings.from_env()
    builder = aggregate_edge_query if mode == "aggregate" else provenance_graph_query
    query, params = builder(entity_type, relation_type, entity_name, limit)
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    try:
        with driver.session(database=config.database) as session:
            return [dict(record) for record in session.run(query, **params)]
    finally:
        driver.close()


def render_interactive_graph(nodes, edges, width):
    try:
        from streamlit_agraph import Config, Edge, Node, agraph
    except ImportError:
        st.warning("未安装 streamlit-agraph，无法渲染交互式图谱。")
        st.code(
            "conda run -n env_agent python -m pip install streamlit-agraph==0.0.45",
            language="powershell",
        )
        return None
    component_nodes = [Node(**node) for node in nodes]
    component_edges = [Edge(**edge) for edge in edges]
    config = Config(
        width=int(width),
        height=650,
        directed=True,
        physics=True,
        hierarchical=False,
        nodeHighlightBehavior=True,
        highlightColor="#F6C7BF",
    )
    return agraph(nodes=component_nodes, edges=component_edges, config=config)


def render_neo4j_view_panel():
    st.subheader("从 Neo4j 查看图谱")
    st.caption("仅在点击查询后读取 Neo4j；支持聚合视图和包含断言、证据元数据的溯源视图。")
    with st.form("neo4j_graph_query"):
        mode_label = st.radio("图谱视图", ("聚合视图", "溯源视图"), horizontal=True)
        entity_name = st.text_input("实体名称包含", placeholder="例如：脚手架")
        entity_type = st.text_input("实体类型", placeholder="例如：设备")
        relation_type = st.text_input("关系类型", placeholder="例如：USES")
        limit = st.slider("最多显示关系或断言数", min_value=1, max_value=300, value=100)
        submitted = st.form_submit_button("查询 Neo4j 图谱", type="primary")

    if submitted:
        mode = "aggregate" if mode_label == "聚合视图" else "provenance"
        try:
            rows = load_neo4j_graph(
                mode,
                entity_type,
                relation_type,
                entity_name,
                limit,
            )
        except Exception as exc:
            st.error(f"无法查询 Neo4j 图谱：{exc}")
            return
        st.session_state["neo4j_graph_view"] = {
            "mode": mode,
            "limit": limit,
            "rows": rows,
        }

    view = st.session_state.get("neo4j_graph_view")
    if not view:
        return
    if not view["rows"]:
        st.info("没有匹配的 Neo4j 图谱数据。")
        return

    nodes, edges, details = graph_records_to_agraph(view["rows"], view["mode"])
    st.caption(
        f"已加载 {len(view['rows'])} 条{'聚合关系' if view['mode'] == 'aggregate' else '关系断言'}，"
        f"共 {len(nodes)} 个节点、{len(edges)} 条边。"
    )
    if len(view["rows"]) == view["limit"]:
        st.warning("结果已达到显示上限；建议缩小筛选条件后再查询。")
    graph_width = st.slider(
        "图谱宽度（像素）",
        min_value=600,
        max_value=1600,
        value=1100,
        step=50,
        key="neo4j_graph_width",
        help="窗口缩放后可调整此宽度；调整不会重新查询 Neo4j。",
    )
    selected_id = render_interactive_graph(nodes, edges, graph_width)
    if selected_id and selected_id in details:
        st.subheader("节点详情")
        st.json(details[selected_id])
    st.dataframe(view["rows"], use_container_width=True, hide_index=True)


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
