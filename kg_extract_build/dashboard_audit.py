"""施工方案审核阶段 1：上传、解析、任务定位和上下文预览。"""

from __future__ import annotations

import hashlib
import os

import pandas as pd
import streamlit as st

from .audit.document_store import AuditDocumentError
from .audit.evidence_reader import (
    block_text_for_export, build_task_evidence_export, group_section_label,
    location_status_label, readable_source, resolve_group_blocks, safe_export_filename, task_option_label,
)
from .audit.persistence import MySQLAuditStore
from .audit.preview import AuditPreview, create_audit_preview
from .audit.settings import AUDIT_CONVERSION_TIMEOUT, AUDIT_DOC_CONVERTER, AUDIT_STORAGE_DIR, LIBREOFFICE_PATH
from .audit.bindings import build_task_bindings
from .audit.task_library import load_published_task_library
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


def _render_environment_health(preview: AuditPreview | None = None) -> None:
    with st.expander("环境与数据域健康检查", expanded=False):
        try:
            library = preview.task_library if preview is not None else load_published_task_library()
            bindings = preview.bindings if preview is not None else build_task_bindings(library)
            st.write(f"任务库：{library.version}（{len(library.tasks)} 项）")
            st.write(f"任务库哈希：{library.sha256}")
            st.write(f"任务绑定：{len(bindings)} 项")
        except Exception as exc:
            st.error(f"任务库健康检查失败：{exc}")
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


def _render_run_lookup() -> None:
    st.subheader("历史审核运行回读")
    st.caption("不依赖当前上传文件；数据库中的时间按 UTC 保存，以下同时显示北京时间。")
    run_id = st.text_input("输入已创建的 run_id", key="audit_history_run_id")
    if not run_id.strip():
        return
    if not _mysql_enabled():
        st.warning("MySQL 持久化未启用，无法回读历史运行。")
        return
    store = MySQLAuditStore.from_env()
    try:
        run = store.load_run(run_id.strip())
        if run is None:
            st.warning("未找到该审核运行。")
        else:
            st.json(run)
    except Exception as exc:
        st.error(f"读取审核运行失败：{exc}")
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

    _render_environment_health()
    _render_run_lookup()
    st.divider()
    st.subheader("新建审核运行")

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

    preview_tab, task_tab, context_tab = st.tabs(["证据块预览", "任务证据阅读器", "审核上下文"])
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
        export = build_task_evidence_export(preview)
        st.download_button("下载全部任务证据 CSV", export.to_csv(index=False).encode("utf-8-sig"),
                           file_name=safe_export_filename(parsed.document.original_filename), mime="text/csv")
        tasks_by_id = {task.task_id: task for task in preview.task_library.tasks}
        selected_task_id = st.selectbox("选择任务", list(tasks_by_id), format_func=lambda item: task_option_label(tasks_by_id[item]))
        task, location = tasks_by_id[selected_task_id], preview.locations[selected_task_id]
        st.markdown(f"#### {task.name}")
        summary = st.columns(3)
        summary[0].write(f"**预期章节**：{task.section}")
        summary[1].write(f"**定位状态**：{location_status_label(location.status)}")
        primary_group = location.evidence_groups[0] if location.evidence_groups else None
        summary[2].write(f"**系统定位章节**：{group_section_label(primary_group) or '—'}")
        if not location.evidence_groups:
            st.info("系统没有找到该任务对应的候选证据。" + (f"\n\n说明：{location.diagnostic}" if location.diagnostic else ""))
        else:
            selected_group = primary_group
            if location.status == "ambiguous":
                group_options = list(range(len(location.evidence_groups)))
                index = st.selectbox("查看候选证据", group_options, format_func=lambda item: f"候选{item + 1}{'（系统首选）' if item == 0 else ''}｜{group_section_label(location.evidence_groups[item])}")
                selected_group = location.evidence_groups[index]
            st.markdown("#### 系统首选证据" if selected_group is primary_group else "#### 候选证据")
            image_map = {image.image_id: image for image in parsed.images}
            blocks = resolve_group_blocks(parsed, selected_group)
            for block in blocks:
                if block.block_type == "heading":
                    st.markdown(f"##### {block.raw_text}")
                elif block.block_type == "table" and block.table_json:
                    st.dataframe(pd.DataFrame(block.table_json.get("rows", [])), use_container_width=True, hide_index=True)
                elif block.raw_text:
                    st.write(block.raw_text)
                for image_id in block.image_refs:
                    image = image_map.get(image_id)
                    if image and image.stored_path.is_file():
                        st.image(str(image.stored_path), width=360)
                    else:
                        st.warning("图片文件不可用。")
            with st.expander("查看来源位置"):
                for block in blocks:
                    st.write(f"章节：{' / '.join(block.section_path) or '未归属章节'}；来源：{readable_source(block)}")
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
