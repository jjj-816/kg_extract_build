"""施工方案审核阶段 1：上传、解析、任务定位和上下文预览。"""

from __future__ import annotations

import hashlib
import os

import pandas as pd
import streamlit as st

from .audit.document_store import AuditDocumentError
from .audit.persistence import MySQLAuditStore
from .audit.preview import AuditPreview, create_audit_preview
from .audit.settings import AUDIT_CONVERSION_TIMEOUT, AUDIT_DOC_CONVERTER, AUDIT_STORAGE_DIR, LIBREOFFICE_PATH
from .audit.word_converter import doc_conversion_capability


WORK_TYPE_OPTIONS = ["动土作业", "动火作业", "吊装作业", "受限空间作业", "临时用电作业", "高处作业"]


def _load_preview(uploaded_file) -> tuple[AuditPreview | None, str | None]:
    data = uploaded_file.getvalue()
    upload_hash = hashlib.sha256(uploaded_file.name.encode("utf-8") + b"\0" + data).hexdigest()
    state_key = "audit_preview_upload_hash"
    if st.session_state.get(state_key) == upload_hash:
        return st.session_state.get("audit_preview"), None
    try:
        preview = create_audit_preview(uploaded_file.name, data)
    except (AuditDocumentError, OSError, RuntimeError, ValueError) as exc:
        return None, str(exc)
    st.session_state[state_key] = upload_hash
    st.session_state["audit_preview"] = preview
    return preview, None


def _mysql_enabled() -> bool:
    return os.getenv("KG_MYSQL_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _render_environment_health(preview: AuditPreview) -> None:
    with st.expander("环境与数据域健康检查", expanded=False):
        st.write(f"任务库：{preview.task_library.version}（{len(preview.task_library.tasks)} 项）")
        st.write(f"任务库哈希：{preview.task_library.sha256}")
        st.write(f"任务绑定：{len(preview.bindings)} 项")
        st.write(f"转换策略：{AUDIT_DOC_CONVERTER}；超时：{AUDIT_CONVERSION_TIMEOUT} 秒")
        st.write(f"LibreOffice：{LIBREOFFICE_PATH}（{'可用' if LIBREOFFICE_PATH.is_file() else '不可用'}）")
        try:
            AUDIT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            st.success(f"文件存储目录可写：{AUDIT_STORAGE_DIR}")
        except OSError as exc:
            st.error(f"文件存储目录不可写：{exc}")
        if not _mysql_enabled():
            st.info("MySQL 持久化未启用；可完成解析与定位预览，但暂不能创建审核运行。")
            return
        store = MySQLAuditStore.from_env()
        try:
            healthy, message = store.schema_health()
            (st.success if healthy else st.warning)(message)
        except Exception as exc:
            st.error(f"MySQL 健康检查失败：{exc}")
        finally:
            store.close()


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
    if parsed.document.converter_name:
        st.info(f"本次 `.doc` 转换器：{parsed.document.converter_name}；诊断：{parsed.document.conversion_diagnostics.get('validation', {})}")
    if parsed.cover_visual_only:
        st.warning("封面主要为图片，封面信息和签字将转入人工核验；不影响其他章节预览。")
    _render_environment_health(preview)

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
        if parsed.images:
            st.subheader("图片预览")
            for image in parsed.images:
                st.caption(f"{image.source_part} · {image.source_locator} · {' / '.join(next((b.section_path for b in parsed.blocks if image.image_id in b.image_refs), ())) or '未归属章节'}")
                st.image(str(image.stored_path), width=260)
            if parsed.cover_visual_only:
                st.warning("封面为整页图片或主要由图片构成，需要人工核验封面签字。")
    with task_tab:
        rows = preview.task_rows()
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        located = sum(row["定位状态"] != "not_located" for row in rows)
        st.caption(f"已产生全部 {len(rows)} 项定位记录；其中 {located} 项至少有一个候选证据块。")
        selected_task_id = st.selectbox("展开单项任务证据组", [task.task_id for task in preview.task_library.tasks])
        location = preview.locations[selected_task_id]
        st.write(f"定位状态：{location.status}；{location.diagnostic or '已形成候选证据组'}")
        for group in location.evidence_groups:
            st.markdown(f"**{group.group_id}** · 得分 {group.score:.2f} · {' / '.join(group.section_path)}")
            st.caption(f"锚点：{group.anchor_block_id}；支持块：{', '.join(group.supporting_block_ids)}；{group.reason}")
    with context_tab:
        st.text_input("项目或平台名称", key="audit_context_project_name")
        st.number_input("审核基准年份", min_value=2000, max_value=2100, value=2025, step=1, key="audit_context_year")
        st.text_area("作业目的", key="audit_context_work_purpose")
        st.multiselect("涉及作业类型", WORK_TYPE_OPTIONS, key="audit_context_work_types")
        reviewer_name = st.text_input("审核确认人", key="audit_context_reviewer")
        if st.button("确认审核上下文并创建审核运行", type="primary"):
            if not _mysql_enabled():
                st.error("MySQL 持久化未启用，当前不能创建审核运行。")
            else:
                context = {
                    "project_name": st.session_state.get("audit_context_project_name", "").strip(),
                    "audit_year": st.session_state.get("audit_context_year"),
                    "work_purpose": st.session_state.get("audit_context_work_purpose", "").strip(),
                    "work_types": list(st.session_state.get("audit_context_work_types", [])),
                }
                missing = [name for name, value in {
                    "项目或平台名称": context["project_name"], "作业目的": context["work_purpose"],
                    "涉及作业类型": context["work_types"], "审核确认人": reviewer_name.strip(),
                }.items() if not value]
                if missing:
                    st.error("请先填写：" + "、".join(missing))
                    return
                store = MySQLAuditStore.from_env()
                try:
                    healthy, health_message = store.schema_health()
                    if not healthy:
                        st.error(health_message)
                    else:
                        run_id = store.create_confirmed_run(parsed, preview.task_library, context, reviewer_name.strip())
                        st.session_state["audit_run_id"] = run_id
                        st.success(f"已创建审核运行：{run_id}（共 {len(preview.task_library.tasks)} 项待执行任务）")
                except Exception as exc:
                    st.error(f"创建审核运行失败：{exc}")
                finally:
                    store.close()
        query_run_id = st.text_input("回读已创建的 run_id", key="audit_query_run_id")
        if query_run_id.strip() and _mysql_enabled():
            store = MySQLAuditStore.from_env()
            try:
                run = store.load_run(query_run_id.strip())
                if run is None:
                    st.warning("未找到该审核运行。")
                else:
                    st.json(run)
            except Exception as exc:
                st.error(f"读取审核运行失败：{exc}")
            finally:
                store.close()
