"""规范向量索引页面：登记 / 索引管理 / 检索预览。"""

from __future__ import annotations

import os

import streamlit as st
import pandas as pd

from . import settings
from .normative_encoder import EncoderProfile, NormativeEncoder, build_encoder_profile_hash, model_revision
from .normative_indexer import NormativeIndexer
from .normative_persistence import NormativeStore
from .normative_registry import guess_version_year, register_version
from .normative_search import NormativeSearcher, SearchRequest
from .normative_vector_store import build_normative_vector_store
from .persistence import MySQLExperimentStore


def _store():
    backend = MySQLExperimentStore.from_env()
    backend.ensure_normative_audit_schema()
    return NormativeStore(backend)


def _encoder():
    profile = EncoderProfile(
        embedding_model_key="paraphrase-multilingual-MiniLM-L12-v2",
        embedding_model_revision=model_revision(settings.NORM_VECTOR_MODEL_PATH),
        embedding_dimension=384,
        query_prefix="",
        document_prefix="",
        max_input_tokens=128,
    )
    return profile, NormativeEncoder(settings.NORM_VECTOR_MODEL_PATH, profile)


def _spec_documents():
    store = MySQLExperimentStore.from_env()
    rows = store._read(
        "SELECT document_id, file_name, status FROM kg_document "
        "WHERE source_type='spec' AND status IN ('completed', 'completed_empty')"
    )
    return rows


def render_registration_area(store):
    st.subheader("① 规范登记")
    documents = _spec_documents()
    if not documents:
        st.info("暂无已完成的规范文档。请先在'运行实验'页以'规范文件'来源处理文档。")
        return
    options = {f"{d['file_name']}（doc {d['document_id']}）": d for d in documents}
    selected = st.selectbox("选择规范文档", list(options))
    document = options[selected]
    with st.form("register_version_form"):
        display_name = st.text_input("规范名称", value=document["file_name"])
        year = st.number_input("生效年份", min_value=2000, max_value=2100, value=2025)
        status = st.selectbox("状态", ["pending_confirmation", "effective", "superseded", "repealed", "unknown"])
        if st.form_submit_button("登记版本并解析条款"):
            content = _document_content(document["document_id"])
            result = register_version(
                store, document_id=document["document_id"], file_name=document["file_name"],
                content=content, display_name=display_name, effective_year=int(year),
                status=status,
            )
            st.success(f"登记完成：条款 {result['clause_count']} 条，条款集 {result['clause_set_id']}")


def _document_content(document_id):
    store = MySQLExperimentStore.from_env()
    rows = store._read("SELECT content FROM kg_document WHERE document_id=%s", (document_id,))
    return rows[0]["content"] if rows else ""


def delete_normative_version(store, vector_store, profile, version_id: str) -> None:
    """Delete a user-confirmed version only after preserving audit history.

    Every attached vector index is removed through the vector-store lifecycle
    API before the persistence layer removes its indexes, clauses and version.
    """
    refs = store.historical_version_references(version_id)
    if refs:
        raise ValueError("该版本已被历史审核引用，只允许停用，禁止物理删除。")
    for index_row in store.index_rows_for_version(version_id):
        vector_store.delete_index(profile, index_row["index_id"])
    store.delete_version_records(version_id)


def render_index_area(store, profile, encoder):
    st.subheader("② 索引管理")
    versions = store.list_versions()
    if not versions:
        st.info("请先在①登记规范版本。")
        return
    options = {f"{v['display_name']}（{v['version_id']}）": v for v in versions}
    selected = st.selectbox("选择版本", list(options))
    version = options[selected]
    st.caption("统一规范库资产状态")
    overview = store.asset_overview()
    if overview:
        rows = []
        for item in overview:
            if item["version_id"] != version["version_id"]:
                continue
            if not item.get("index_id"):
                state = "索引未就绪"
            elif item.get("version_status") != "effective" or not item.get("metadata_confirmed"):
                state = "元数据待确认"
            elif item.get("index_status") != "ready":
                state = "索引未就绪"
            elif not item.get("audit_disabled_at"):
                state = "已启用"
            else:
                state = "索引就绪但未启用"
            rows.append({**item, "asset_state": state})
        if rows:
            st.dataframe(pd.DataFrame(rows)[[
                "canonical_name", "standard_code", "version_year", "effective_year",
                "metadata_confirmed", "clause_count", "index_id", "collection_name",
                "release_count", "family_consistency", "asset_state",
            ]], use_container_width=True, hide_index=True)
            if any(row.get("family_consistency") == "mismatch" for row in rows):
                st.warning(
                    "规范族不一致：该版本名称或标准号与当前规范族不匹配，"
                    "已禁止其作为替代链候选或进入统一规范库。请核对后停用或彻底删除。"
                )
            ready = [
                row for row in rows
                if row.get("index_status") == "ready"
                and row.get("family_consistency") != "mismatch"
            ]
            manageable = [row for row in rows if row.get("index_id")]
            if ready:
                selected_index = st.selectbox(
                    "选择要启用/停用的索引",
                    ready,
                    format_func=lambda row: f"{row['display_name']} · {row['index_id']}",
                    key=f"normative_enable_index_{version['version_id']}",
                )
                if not selected_index.get("audit_disabled_at"):
                    if st.button("停用统一规范库", key=f"disable_normative_{selected_index['index_id']}"):
                        store.set_audit_enabled(selected_index["index_id"], False)
                        st.success("已停用；规范资产和历史发布快照保留。")
                        st.rerun()
                else:
                    if st.button("启用统一规范库", key=f"enable_normative_{selected_index['index_id']}"):
                        if selected_index.get("version_status") == "effective" and selected_index.get("metadata_confirmed"):
                            store.set_audit_enabled(selected_index["index_id"], True)
                            st.success("已启用，将进入后续正式审核。")
                            st.rerun()
                        st.error("版本必须为 effective 且元数据已确认后才能启用。")
            if manageable:
                management_index = next(
                    (row for row in manageable if row.get("index_id") == (ready[0].get("index_id") if ready else None)),
                    manageable[0],
                )
                if management_index.get("family_consistency") == "mismatch" and not management_index.get("audit_disabled_at"):
                    confirm_disable_mismatch = st.checkbox(
                        "我确认停用误挂资产（保留版本、条款和历史记录）",
                        key=f"confirm_disable_mismatched_normative_{management_index['index_id']}",
                    )
                    if confirm_disable_mismatch and st.button(
                        "停用误挂规范资产", key=f"disable_mismatched_normative_{management_index['index_id']}"
                    ):
                        store.set_audit_enabled(management_index["index_id"], False)
                        st.success("误挂规范资产已停用；请继续核对后决定是否彻底删除。")
                        st.rerun()
                st.divider()
                st.warning("以下是两类独立的危险操作，请分别确认；删除索引不会删除规范版本和条款。")
                confirm_index_delete = st.checkbox(
                    "我确认删除该规范索引（保留规范版本、条款和发布快照）",
                    key=f"confirm_normative_index_delete_{management_index['index_id']}",
                )
                if confirm_index_delete and st.button("删除索引（保留版本和条款）", key=f"delete_normative_index_{management_index['index_id']}"):
                    try:
                        build_normative_vector_store().delete_index(profile, management_index["index_id"])
                        store.delete_index_records(management_index["index_id"])
                        st.success("索引已删除，规范版本和条款已保留，可重新构建索引。")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"删除索引失败，已停止后续清理：{exc}")
                confirm_version_delete = st.checkbox(
                    "我确认彻底删除该规范版本（同时删除条款、索引及关联向量）",
                    key=f"confirm_normative_version_delete_{version['version_id']}",
                )
                if confirm_version_delete and st.button("彻底删除规范版本", key=f"delete_normative_version_{version['version_id']}"):
                    try:
                        delete_normative_version(
                            store, build_normative_vector_store(), profile, version["version_id"],
                        )
                        st.success("规范版本及其索引、条款已彻底删除。")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"彻底删除失败，系统保留可诊断状态：{exc}")
    if st.button("构建 / 重建索引"):
        indexer = NormativeIndexer(store, build_normative_vector_store(), encoder, profile)
        result = indexer.build_index(version["version_id"])
        st.write(result)
    release_name = st.text_input("发布版名称")
    if st.button("创建发布版"):
        indexer = NormativeIndexer(store, build_normative_vector_store(), encoder, profile)
        index_rows = store.index_rows([r["index_id"] for r in store._read(
            "SELECT index_id FROM kg_normative_index WHERE version_id=%s AND status='ready'",
            (version["version_id"],),
        )])
        release_id = indexer.build_release(release_name or "mvp-release", [r["index_id"] for r in index_rows])
        st.success(f"发布版：{release_id}")


def render_search_preview(searcher_class, searcher, releases):
    st.subheader("③ 发布快照检索预览（仅用于复现/调试）")
    st.caption("正式施工方案审核不使用此处的发布版选择，而是自动使用已启用且索引就绪的统一规范库。")
    if not releases:
        st.info("暂无已发布的规范索引版本，请先在②创建发布版。")
        return
    with st.form("search_preview_form"):
        query = st.text_input("查询文本")
        year = st.number_input("审核年份", min_value=2000, max_value=2100, value=2025)
        release_id = st.selectbox("规范索引发布版", list(releases))
        top_k = st.slider("Top-K（条款数）", 1, 20, 5)
        if st.form_submit_button("检索"):
            result = searcher.search(SearchRequest(query, int(year), release_id, {}, int(top_k)))
            st.dataframe(result["evidence"])
            st.write(result["coverage"])
            st.write(result["retrieval_trace"])


def render_normative_page():
    if not settings.NORM_MILVUS_ENABLED:
        st.warning("KG_NORM_MILVUS_ENABLED 未开启，检索预览不可用。请在 .env 开启并启动 Milvus 服务。")
    store = _store()
    profile, encoder = _encoder()
    render_registration_area(store)
    render_index_area(store, profile, encoder)
    releases = {r["release_id"]: r["release_name"] for r in store._read(
        "SELECT release_id, release_name FROM kg_normative_index_release WHERE status='published'"
    )}
    searcher = NormativeSearcher(store, build_normative_vector_store(), encoder, profile)
    render_search_preview(NormativeSearcher, searcher, releases)
    encoder.close()
