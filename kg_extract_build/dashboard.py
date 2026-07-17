import json
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from kg_extract_build.persistence import MySQLExperimentStore
from kg_extract_build.vector_store import build_vector_store


try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"), override=False)
except ImportError:
    pass


st.set_page_config(
    page_title="KG Experiment Console",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --kg-primary: #2563EB;
        --kg-accent: #059669;
        --kg-bg: #F8FAFC;
        --kg-fg: #0F172A;
        --kg-muted: #F1F5F9;
        --kg-border: #E2E8F0;
    }
    .stApp { background: var(--kg-bg); color: var(--kg-fg); }
    [data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid var(--kg-border);
        border-radius: 12px;
        padding: 16px;
    }
    [data-testid="stSidebar"] { border-right: 1px solid var(--kg-border); }
    .kg-eyebrow {
        color: var(--kg-primary);
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    .kg-subtle { color: #475569; margin-top: -0.5rem; }
    .stButton > button, .stDownloadButton > button {
        min-height: 44px;
        border-radius: 8px;
    }
    @media (prefers-reduced-motion: reduce) {
        * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def connection_config():
    with st.sidebar.expander("MySQL 连接", expanded=True):
        host = st.text_input("主机", os.getenv("KG_MYSQL_HOST", "127.0.0.1"))
        port = st.number_input(
            "端口",
            min_value=1,
            max_value=65535,
            value=int(os.getenv("KG_MYSQL_PORT", "3306")),
        )
        user = st.text_input("用户", os.getenv("KG_MYSQL_USER", "root"))
        password = st.text_input(
            "密码",
            os.getenv("KG_MYSQL_PASSWORD", ""),
            type="password",
        )
        database = st.text_input(
            "数据库",
            os.getenv("KG_MYSQL_DATABASE", "kg_experiments"),
        )
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password,
        "database": database,
        "charset": "utf8mb4",
        "cursorclass": dict_cursor_class(),
    }


def dict_cursor_class():
    try:
        import pymysql
    except ImportError:
        return None
    return pymysql.cursors.DictCursor


def query(config, sql, params=None):
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("缺少 pymysql，请先安装 requirements.txt") from exc

    options = dict(config)
    if options.get("cursorclass") is None:
        options["cursorclass"] = pymysql.cursors.DictCursor
    connection = pymysql.connect(**options)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params or ())
            return list(cursor.fetchall())
    finally:
        connection.close()


def scalar(config, sql, params=None, default=0):
    rows = query(config, sql, params)
    if not rows:
        return default
    return next(iter(rows[0].values()))


def frame(rows):
    return pd.DataFrame(rows) if rows else pd.DataFrame()


@dataclass(frozen=True)
class DeletionResult:
    deleted: bool
    state: str
    message: str


def _experiment_store(config):
    options = {
        key: config[key]
        for key in ("host", "port", "user", "password", "database", "charset")
        if key in config
    }
    return MySQLExperimentStore(**options)


def delete_run_with_vectors(config: dict, run_id: str) -> DeletionResult:
    """Delete vectors, persist a resume marker, then cascade the SQL parent."""
    store = _experiment_store(config)
    state = store.get_deletion_state(run_id)
    if state is None:
        return DeletionResult(False, "missing", "未找到实验批次。")
    if state != "active":
        return DeletionResult(False, state, "批次删除已进入恢复状态，请使用恢复删除。")
    vector_store = build_vector_store()
    try:
        vector_store.delete_segments_by_run(run_id)
    finally:
        vector_store.close()
    if not store.mark_vectors_deleted_sql_pending(run_id):
        return DeletionResult(False, "active", "无法记录向量删除状态，SQL 数据未删除。")
    if store.delete_run(run_id):
        return DeletionResult(True, "deleted", "实验批次及关联数据已删除。")
    return DeletionResult(
        False,
        "vectors_deleted_sql_pending",
        "向量已删除，但 SQL 数据仍保留；请使用恢复删除。",
    )


def resume_pending_run_deletion(config: dict, run_id: str) -> DeletionResult:
    """Complete only the SQL phase for a run whose vectors are already deleted."""
    store = _experiment_store(config)
    if store.get_deletion_state(run_id) != "vectors_deleted_sql_pending":
        return DeletionResult(False, "active", "该批次不需要恢复删除。")
    if store.delete_run(run_id):
        return DeletionResult(True, "deleted", "恢复删除完成。")
    return DeletionResult(False, "vectors_deleted_sql_pending", "恢复删除未完成，请稍后重试。")


def render_delete_panel(config, selected_run):
    """Render the explicit confirmation gate for deleting one completed run."""
    run_id = selected_run["run_id"]
    status = selected_run["status"]
    deletion_state = selected_run.get("deletion_state", "active")
    with st.expander("危险操作：永久删除此实验批次"):
        st.caption(
            " · ".join(
                [
                    f"名称：{selected_run['run_name']}",
                    f"ID：{run_id}",
                    f"状态：{status}",
                    f"文档数：{selected_run['document_count']}",
                    f"最终三元组：{selected_run['final_triplet_count']}",
                ]
            )
        )
        confirmed = st.checkbox(
            f"我确认永久删除批次 {run_id} 及其全部关联数据",
            key=f"confirm_delete_{run_id}",
        )
        pending = deletion_state == "vectors_deleted_sql_pending"
        if pending:
            st.warning("向量已删除，SQL 批次数据仍待删除。恢复操作不会再次访问 Milvus。")
        if st.button(
            "恢复删除（仅删除 SQL 数据）" if pending else "永久删除此实验批次",
            type="primary",
            disabled=(status == "running" or not confirmed),
        ):
            try:
                result = (
                    resume_pending_run_deletion(config, run_id)
                    if pending
                    else delete_run_with_vectors(config, run_id)
                )
            except Exception as exc:
                st.error(f"删除失败，未删除 SQL 批次：{exc}")
                return
            if result.deleted:
                st.session_state.pop("preferred_run_id", None)
                st.success(result.message)
                st.rerun()
            else:
                st.warning(result.message)
        if status == "running":
            st.warning("运行中的批次不能删除。")


def render_header(title, description):
    st.markdown('<div class="kg-eyebrow">KG Experiment Console</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<p class="kg-subtle">{description}</p>', unsafe_allow_html=True)


def run_options(config):
    return query(
        config,
        """
        SELECT run_id, run_name, status, deletion_state, started_at
        FROM kg_experiment_run
        ORDER BY started_at DESC
        LIMIT 200
        """,
    )


def choose_run(config, key):
    runs = run_options(config)
    if not runs:
        st.info("暂无实验运行记录。")
        return None
    labels = {
        item["run_id"]: (
            f"{item['run_name']} · {item['status']} · "
            f"{item['started_at']}"
        )
        for item in runs
    }
    run_ids = list(labels)
    preferred = st.session_state.get("preferred_run_id")
    default_index = run_ids.index(preferred) if preferred in run_ids else 0
    selected = st.selectbox(
        "实验批次",
        options=run_ids,
        index=default_index,
        format_func=lambda value: labels[value],
        key=key,
    )
    return selected


def overview_page(config):
    render_header("实验总览", "快速确认实验规模、成功情况与核心产物。")
    metrics = {
        "实验批次": scalar(config, "SELECT COUNT(*) AS value FROM kg_experiment_run"),
        "文档": scalar(config, "SELECT COUNT(*) AS value FROM kg_document"),
        "切片": scalar(config, "SELECT COUNT(*) AS value FROM kg_document_chunk"),
        "最终三元组": scalar(
            config,
            "SELECT COUNT(*) AS value FROM kg_triplet WHERE stage='final'",
        ),
    }
    columns = st.columns(4)
    for column, (label, value) in zip(columns, metrics.items()):
        column.metric(label, value)

    left, right = st.columns([3, 2])
    with left:
        st.subheader("最近实验")
        rows = query(
            config,
            """
            SELECT run_name, status, started_at, finished_at, code_commit
            FROM kg_experiment_run
            ORDER BY started_at DESC
            LIMIT 20
            """,
        )
        st.dataframe(frame(rows), use_container_width=True, hide_index=True)
    with right:
        st.subheader("运行状态")
        rows = query(
            config,
            """
            SELECT status, COUNT(*) AS count
            FROM kg_experiment_run
            GROUP BY status
            ORDER BY count DESC
            """,
        )
        chart = frame(rows)
        if not chart.empty:
            st.bar_chart(chart.set_index("status"))
        else:
            st.info("暂无状态统计。")


def runs_page(config):
    render_header("实验批次", "查看模型、Schema、参数快照和运行错误，旧实验不会被覆盖。")
    status = st.selectbox(
        "状态筛选",
        ["全部", "running", "completed", "completed_with_errors", "failed"],
    )
    where = "" if status == "全部" else "WHERE status=%s"
    params = () if status == "全部" else (status,)
    rows = query(
        config,
        f"""
        SELECT run_id, run_name, status, deletion_state, code_commit, started_at, finished_at,
               error_message
        FROM kg_experiment_run
        {where}
        ORDER BY started_at DESC
        LIMIT 500
        """,
        params,
    )
    st.dataframe(frame(rows), use_container_width=True, hide_index=True)

    run_id = choose_run(config, "runs_detail")
    if run_id:
        detail = query(
            config,
            """
            SELECT run_id, run_name, status, deletion_state, config_snapshot, schema_snapshot,
                   error_message,
                   (SELECT COUNT(*) FROM kg_document WHERE run_id=%s) AS document_count,
                   (SELECT COUNT(*) FROM kg_triplet
                    WHERE run_id=%s AND stage='final') AS final_triplet_count
            FROM kg_experiment_run
            WHERE run_id=%s
            """,
            (run_id, run_id, run_id),
        )[0]
        config_tab, schema_tab, error_tab = st.tabs(["配置快照", "Schema 快照", "错误"])
        with config_tab:
            st.json(detail.get("config_snapshot") or {})
        with schema_tab:
            st.json(detail.get("schema_snapshot") or {})
        with error_tab:
            st.code(detail.get("error_message") or "无错误", language="text")
        render_delete_panel(config, detail)


def documents_page(config):
    render_header("文档追踪", "沿着原文、切片、实体、检索和三元组逐层检查结果。")
    run_id = choose_run(config, "document_run")
    if not run_id:
        return
    documents = query(
        config,
        """
        SELECT document_id, file_name, status
        FROM kg_document
        WHERE run_id=%s
        ORDER BY file_name
        """,
        (run_id,),
    )
    if not documents:
        st.info("该实验没有文档记录。")
        return
    labels = {
        item["document_id"]: f"{item['file_name']} · {item['status']}"
        for item in documents
    }
    document_id = st.selectbox(
        "文档",
        list(labels),
        format_func=lambda value: labels[value],
    )
    tabs = st.tabs(["原文", "切片", "实体", "检索", "三元组"])

    with tabs[0]:
        row = query(
            config,
            """
            SELECT file_name, source_type, content_hash, status, error_message,
                   content
            FROM kg_document
            WHERE document_id=%s
            """,
            (document_id,),
        )[0]
        st.caption(
            f"类型：{row['source_type']} · 状态：{row['status']} · "
            f"SHA-256：{row['content_hash']}"
        )
        if row.get("error_message"):
            st.error(row["error_message"])
        st.text_area("文档原文", row["content"], height=520, disabled=True)

    with tabs[1]:
        chunk_type = st.selectbox(
            "切片类型",
            ["entity_extraction", "retrieval_sentence"],
        )
        rows = query(
            config,
            """
            SELECT chunk_id, chunk_index, start_offset, end_offset,
                   content_hash, milvus_id, content
            FROM kg_document_chunk
            WHERE document_id=%s AND chunk_type=%s
            ORDER BY chunk_index
            """,
            (document_id, chunk_type),
        )
        st.dataframe(frame(rows), use_container_width=True, hide_index=True)

    with tabs[2]:
        rows = query(
            config,
            """
            SELECT stage, entity_name, entity_type, standard_name, aliases,
                   source_type
            FROM kg_entity
            WHERE document_id=%s
            ORDER BY stage, entity_name
            """,
            (document_id,),
        )
        st.dataframe(frame(rows), use_container_width=True, hide_index=True)

    with tabs[3]:
        rows = query(
            config,
            """
            SELECT entity_name, query_alias, hit_rank, match_type,
                   similarity_score, chunk_id, sentence
            FROM kg_retrieval_result
            WHERE document_id=%s
            ORDER BY entity_name, query_alias, hit_rank
            """,
            (document_id,),
        )
        st.dataframe(frame(rows), use_container_width=True, hide_index=True)

    with tabs[4]:
        stage = st.radio("结果阶段", ["final", "raw"], horizontal=True)
        rows = query(
            config,
            """
            SELECT entity_name, head, head_type, relation_name, tail, tail_type,
                   source_kind, is_valid
            FROM kg_triplet
            WHERE document_id=%s AND stage=%s
            ORDER BY relation_name, head, tail
            """,
            (document_id, stage),
        )
        data = frame(rows)
        st.dataframe(data, use_container_width=True, hide_index=True)
        if not data.empty:
            st.download_button(
                "导出当前三元组 CSV",
                data.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"triplets-{document_id}-{stage}.csv",
                mime="text/csv",
            )


def llm_page(config):
    render_header("LLM 调用", "检查每一次 Prompt、原始响应、解析结果、耗时和错误。")
    run_id = choose_run(config, "llm_run")
    if not run_id:
        return
    stages = query(
        config,
        "SELECT DISTINCT stage FROM kg_llm_call WHERE run_id=%s ORDER BY stage",
        (run_id,),
    )
    options = ["全部"] + [item["stage"] for item in stages]
    stage = st.selectbox("处理阶段", options)
    where = "run_id=%s"
    params = [run_id]
    if stage != "全部":
        where += " AND stage=%s"
        params.append(stage)
    rows = query(
        config,
        f"""
        SELECT llm_call_id, stage, entity_name, model_name, latency_ms,
               success, error_message, created_at
        FROM kg_llm_call
        WHERE {where}
        ORDER BY llm_call_id DESC
        LIMIT 1000
        """,
        tuple(params),
    )
    st.dataframe(frame(rows), use_container_width=True, hide_index=True)
    if not rows:
        return
    call_id = st.selectbox(
        "调用详情",
        [item["llm_call_id"] for item in rows],
        format_func=lambda value: f"LLM Call #{value}",
    )
    detail = query(
        config,
        """
        SELECT prompt, raw_response, parsed_result, metadata_json, error_message
        FROM kg_llm_call
        WHERE llm_call_id=%s
        """,
        (call_id,),
    )[0]
    prompt_tab, response_tab, parsed_tab, metadata_tab = st.tabs(
        ["Prompt", "原始响应", "解析结果", "元数据"]
    )
    with prompt_tab:
        st.code(detail.get("prompt") or "", language="text", wrap_lines=True)
    with response_tab:
        st.code(detail.get("raw_response") or "", language="json", wrap_lines=True)
    with parsed_tab:
        st.json(detail.get("parsed_result") or {})
    with metadata_tab:
        st.json(detail.get("metadata_json") or {})
        if detail.get("error_message"):
            st.error(detail["error_message"])


def dot_escape(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def graph_page(config):
    render_header("知识图谱", "按实验或文档查看最终实体关系，并保留表格导出能力。")
    run_id = choose_run(config, "graph_run")
    if not run_id:
        return
    documents = query(
        config,
        """
        SELECT document_id, file_name
        FROM kg_document
        WHERE run_id=%s
        ORDER BY file_name
        """,
        (run_id,),
    )
    options = [None] + [item["document_id"] for item in documents]
    labels = {None: "全部文档"}
    labels.update({item["document_id"]: item["file_name"] for item in documents})
    document_id = st.selectbox(
        "文档范围",
        options,
        format_func=lambda value: labels[value],
    )
    sql = """
        SELECT head, head_type, relation_name, tail, tail_type
        FROM kg_triplet
        WHERE run_id=%s AND stage='final'
    """
    params = [run_id]
    if document_id is not None:
        sql += " AND document_id=%s"
        params.append(document_id)
    sql += " ORDER BY relation_name, head, tail LIMIT 500"
    rows = query(config, sql, tuple(params))
    if not rows:
        st.info("当前范围内没有最终三元组。")
        return

    lines = [
        "digraph KG {",
        'graph [rankdir="LR", bgcolor="transparent"];',
        'node [shape="box", style="rounded,filled", fillcolor="#EFF6FF", color="#93C5FD", fontname="Microsoft YaHei"];',
        'edge [color="#64748B", fontname="Microsoft YaHei"];',
    ]
    for item in rows:
        head = dot_escape(item["head"])
        tail = dot_escape(item["tail"])
        relation = dot_escape(item["relation_name"])
        lines.append(f'"{head}" -> "{tail}" [label="{relation}"];')
    lines.append("}")
    st.graphviz_chart("\n".join(lines), use_container_width=True)
    st.dataframe(frame(rows), use_container_width=True, hide_index=True)


def setup_help():
    st.error("无法读取实验数据库。")
    st.markdown(
        """
        请确认：

        1. 已创建数据库，例如 `CREATE DATABASE kg_experiments CHARACTER SET utf8mb4;`
        2. 已执行本目录的 `schema.sql`，或启用 `KG_MYSQL_AUTO_INIT=1`
        3. 侧边栏连接参数正确
        4. 已安装 `pymysql`
        """
    )


from kg_extract_build.dashboard_evaluation import render_evaluation_page
from kg_extract_build.dashboard_run import render_run_page

RUN_PAGE = "运行实验"
EVALUATION_PAGE = "实验评估"
OVERVIEW_PAGE = "实验总览"
RUNS_PAGE = "实验批次"
DOCUMENTS_PAGE = "文档追踪"
LLM_PAGE = "LLM 调用"
GRAPH_PAGE = "知识图谱"

requested_page = st.session_state.pop("requested_navigation_page", None)
if requested_page is not None:
    st.session_state["navigation_page"] = requested_page

page = st.sidebar.radio(
    "导航",
    [
        RUN_PAGE,
        EVALUATION_PAGE,
        OVERVIEW_PAGE,
        RUNS_PAGE,
        DOCUMENTS_PAGE,
        LLM_PAGE,
        GRAPH_PAGE,
    ],
    key="navigation_page",
)

if page == RUN_PAGE:
    render_run_page()
elif page == EVALUATION_PAGE:
    render_evaluation_page()
else:
    config = connection_config()
    try:
        with st.spinner("正在读取实验数据库…"):
            if page == OVERVIEW_PAGE:
                overview_page(config)
            elif page == RUNS_PAGE:
                runs_page(config)
            elif page == DOCUMENTS_PAGE:
                documents_page(config)
            elif page == LLM_PAGE:
                llm_page(config)
            else:
                graph_page(config)
    except Exception as exc:
        setup_help()
        with st.expander("错误详情"):
            st.code(str(exc), language="text")
