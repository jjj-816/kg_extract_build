import os

import streamlit as st

from .neo4j_graph import Neo4jGraphSynchronizer
from .persistence import build_experiment_store
from .schema import KGSchema
from .settings import resolve_schema_path

def neo4j_sync_enabled():
    enabled = os.getenv("KG_MYSQL_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    return enabled, "" if enabled else "请先启用 KG_MYSQL_ENABLED=1；图谱同步只读取 MySQL 中可追溯的最终三元组。"


def eligible_runs(rows):
    return [row for row in rows if row.get("status") == "completed" and row.get("deletion_state", "active") == "active"]


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
    labels = {row["run_id"]: f"{row.get('run_name', row['run_id'])} · {row['run_id']}" for row in runs}
    run_ids = st.multiselect("选择要同步的运行批次", list(labels), format_func=labels.get)
    if st.button("同步至 Neo4j", disabled=not run_ids, type="primary"):
        syncer = None
        try:
            syncer = Neo4jGraphSynchronizer.from_env(store, KGSchema(resolve_schema_path()))
            syncer.check_connection()
            results = []
            for run_id in run_ids:
                try:
                    results.append({**syncer.sync_run(run_id).__dict__, "status": "success", "error": ""})
                except Exception as exc:
                    results.append({"run_id": run_id, "status": "failed", "error": str(exc)})
            st.success("Neo4j 同步处理完成")
            st.dataframe(results, use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"Neo4j 同步失败：{exc}")
        finally:
            store.close()
            if syncer is not None:
                syncer.driver.close()
