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
    return NormativeStore(MySQLExperimentStore.from_env())


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
            elif item.get("enabled_for_audit"):
                state = "已启用"
            else:
                state = "索引就绪但未启用"
            rows.append({**item, "asset_state": state})
        if rows:
            st.dataframe(pd.DataFrame(rows)[[
                "canonical_name", "standard_code", "version_year", "effective_year",
                "metadata_confirmed", "clause_count", "index_id", "collection_name",
                "release_count", "asset_state",
            ]], use_container_width=True, hide_index=True)
            ready = [row for row in rows if row.get("index_status") == "ready"]
            if ready:
                selected_index = st.selectbox(
                    "选择要启用/停用的索引",
                    ready,
                    format_func=lambda row: f"{row['display_name']} · {row['index_id']}",
                    key=f"normative_enable_index_{version['version_id']}",
                )
                if selected_index.get("enabled_for_audit"):
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
                st.divider()
                st.warning("以下操作会清理规范资产，请先确认。")
                confirm = st.checkbox("我确认执行规范索引清理", key=f"confirm_normative_delete_{selected_index['index_id']}")
                if confirm and st.button("删除索引（保留版本和条款）", key=f"delete_normative_index_{selected_index['index_id']}"):
                    try:
                        build_normative_vector_store().delete_index(profile, selected_index["index_id"])
                        store.delete_index_records(selected_index["index_id"])
                        st.success("索引已删除，规范版本和条款已保留，可重新构建索引。")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"删除索引失败，已停止后续清理：{exc}")
                if confirm and st.button("彻底删除规范版本", key=f"delete_normative_version_{version['version_id']}"):
                    try:
                        refs = store.historical_version_references(version["version_id"])
                        if refs:
                            st.error("该版本已被历史审核引用，只允许停用，禁止物理删除。")
                        else:
                            build_normative_vector_store().delete_index(profile, selected_index["index_id"])
                            store.delete_version_records(version["version_id"])
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
    st.subheader("③ 检索预览")
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
