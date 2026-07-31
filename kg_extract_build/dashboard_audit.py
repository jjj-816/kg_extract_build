"""施工方案审核阶段 1：上传、解析、任务定位和上下文预览。"""

from __future__ import annotations

import hashlib
import os

import pandas as pd
import streamlit as st

from .audit.document_store import AuditDocumentError
from .audit.persistence import MySQLAuditStore
from .audit.preview import AuditPreview, create_audit_preview
from .audit.word_converter import doc_conversion_capability


WORK_TYPE_OPTIONS = ["动土作业", "动火作业", "吊装作业", "受限空间作业", "临时用电作业", "高处作业"]


def _persist_preview_if_enabled(preview: AuditPreview) -> str | None:
    if os.getenv("KG_MYSQL_ENABLED", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    store = MySQLAuditStore.from_env()
    try:
        store.initialize_schema()
        store.save_parsed_document(preview.parsed_document)
    finally:
        store.close()
    return "已写入 audit_document 和 audit_document_block"


def _load_preview(uploaded_file) -> tuple[AuditPreview | None, str | None]:
    data = uploaded_file.getvalue()
    upload_hash = hashlib.sha256(uploaded_file.name.encode("utf-8") + b"\0" + data).hexdigest()
    state_key = "audit_preview_upload_hash"
    if st.session_state.get(state_key) == upload_hash:
        return st.session_state.get("audit_preview"), None
    try:
        preview = create_audit_preview(uploaded_file.name, data)
        persistence_message = _persist_preview_if_enabled(preview)
    except (AuditDocumentError, OSError, RuntimeError, ValueError) as exc:
        return None, str(exc)
    st.session_state[state_key] = upload_hash
    st.session_state["audit_preview"] = preview
    return preview, persistence_message


def render_audit_page() -> None:
    st.title("施工方案审核")
    st.caption("阶段 1：上传单份 Word、生成证据块、预览 42 项任务定位，并由审核员确认审核上下文。")

    capability = doc_conversion_capability()
    if capability.available:
        st.info(f"`.doc` 转换能力：{capability.message}")
    else:
        st.warning(f"`.doc` 转换能力：{capability.message}；`.docx` 仍可正常预览。")

    uploaded_file = st.file_uploader("上传施工方案 Word", type=["docx", "doc"], accept_multiple_files=False)
    if uploaded_file is None:
        st.info("一次只能上传一份施工方案。上传后将生成结构化证据块，不会调用 LLM、Milvus、Neo4j 或 JSA 服务。")
        return
    preview, message = _load_preview(uploaded_file)
    if preview is None:
        st.error(f"无法解析施工方案：{message}")
        return
    if message:
        st.success(message)

    parsed = preview.parsed_document
    metrics = st.columns(5)
    metrics[0].metric("段落", parsed.paragraph_count)
    metrics[1].metric("表格", parsed.table_count)
    metrics[2].metric("图片引用", parsed.image_count)
    metrics[3].metric("证据块", len(parsed.blocks))
    metrics[4].metric("审核任务", len(preview.task_library.tasks))
    st.caption(
        f"源文件：{parsed.document.original_filename} · SHA-256：{parsed.document.content_hash[:16]}… · "
        f"任务库：{preview.task_library.version}"
    )
    if parsed.cover_visual_only:
        st.warning("封面主要为图片，封面信息和签字将转入人工核验；不影响其他章节预览。")

    preview_tab, task_tab, context_tab = st.tabs(["证据块预览", "任务定位预览", "审核上下文"])
    with preview_tab:
        block_rows = [
            {
                "序号": block.ordinal,
                "类型": block.block_type,
                "章节": " / ".join(block.section_path),
                "位置": block.source_locator,
                "文本预览": block.raw_text[:300],
                "图片": len(block.image_refs),
            }
            for block in parsed.blocks
        ]
        st.dataframe(pd.DataFrame(block_rows), use_container_width=True, hide_index=True)
    with task_tab:
        rows = preview.task_rows()
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        located = sum(row["定位状态"] != "not_located" for row in rows)
        st.caption(f"已产生全部 {len(rows)} 项定位记录；其中 {located} 项至少有一个候选证据块。")
    with context_tab:
        st.text_input("项目或平台名称", key="audit_context_project_name")
        st.number_input("审核基准年份", min_value=2000, max_value=2100, value=2025, step=1, key="audit_context_year")
        st.text_area("作业目的", key="audit_context_work_purpose")
        st.multiselect("涉及作业类型", WORK_TYPE_OPTIONS, key="audit_context_work_types")
        st.info("当前仅保存页面会话中的审核上下文；下一阶段将把确认后的上下文创建为独立审核运行。")
