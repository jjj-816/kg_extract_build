"""施工方案审核阶段 1：上传、解析、任务定位和上下文预览。"""

from __future__ import annotations

import hashlib
import os

import pandas as pd
import streamlit as st

from .audit.document_store import AuditDocumentError
from .audit.executor import AuditOrchestrator
from .audit.evidence_reader import (
    build_task_evidence_export, group_section_label,
    location_status_label, readable_source, resolve_group_blocks, safe_export_filename, table_rows, task_option_label,
)
from .audit.persistence import MySQLAuditStore
from .audit.reporting import RESULT_GROUPS, build_draft_report, build_stage2_result_export, stage2_result_groups
from .audit.report_service import ReportPublishBlocked, ReportReauditRequired, append_review_action, create_correction_version, export_report_snapshot, freeze_report_snapshot
from .audit.ui_state import execution_summary, pending_review_task_ids, split_evidence, version_summary
from .audit.risk_catalog import RiskCatalogError, detect_work_codes, load_risk_catalog
from .audit.preview import AuditPreview, create_audit_preview
from .audit.settings import AUDIT_CONVERSION_TIMEOUT, AUDIT_DOC_CONVERTER, AUDIT_STORAGE_DIR, LIBREOFFICE_PATH
from .audit.bindings import build_task_bindings
from .audit.task_library import load_published_task_library
from .audit.word_converter import doc_conversion_capability
from .audit.provider_runtime import build_structured_model
from .audit.normative_scope import NormativeScope
from .audit.production_composition import ProductionAuditComposition
from .audit.normative_recognition import freeze_confirmed_candidates, recognize_declared_norms
from .run_config import PROVIDERS, resolve_provider_api_key


WORK_TYPE_OPTIONS = ["动土作业", "动火作业", "吊装作业", "受限空间作业", "临时用电作业", "高处作业", "上位系统类作业"]


def _load_preview(uploaded_file) -> tuple[AuditPreview | None, str | None]:
    data = uploaded_file.getvalue()
    upload_hash = hashlib.sha256(uploaded_file.name.encode("utf-8") + b"\0" + data).hexdigest()
    state_key = "audit_preview_upload_hash"
    if st.session_state.get(state_key) == upload_hash:
        return st.session_state.get("audit_preview"), None
    st.session_state.pop("audit_stage2_report", None)
    st.session_state.pop("audit_stage2_image_paths", None)
    for key in ("audit_work_type_detection_document", "audit_context_work_types", "audit_work_types_confirmed", "audit_unmatched_codes_confirmed"):
        st.session_state.pop(key, None)
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


def _risk_work_detection(preview: AuditPreview) -> dict:
    """从 ARR-001 的已定位证据提取风险作业编号及目录映射。"""
    catalog = load_risk_catalog()
    location = preview.locations["ARR-001"]
    blocks = resolve_group_blocks(preview.parsed_document, location.evidence_groups[0] if location.evidence_groups else None)
    detected = detect_work_codes(blocks, catalog)
    return {
        "detected_work_codes": [item.as_dict() for item in detected],
        "detected_work_types": sorted({work_type for item in detected for work_type in item.work_types}),
        "risk_catalog_version": catalog.version,
    }


def _render_work_type_confirmation(preview: AuditPreview) -> dict | None:
    st.markdown("#### 作业类型识别与确认")
    try:
        detection = _risk_work_detection(preview)
    except RiskCatalogError as exc:
        st.error(f"风险作业目录不可用，无法确认作业类型：{exc}")
        return None
    document_key = preview.parsed_document.document.document_id
    if st.session_state.get("audit_work_type_detection_document") != document_key:
        st.session_state["audit_work_type_detection_document"] = document_key
        st.session_state["audit_context_work_types"] = list(detection["detected_work_types"])
        st.session_state["audit_work_types_confirmed"] = False
        st.session_state["audit_unmatched_codes_confirmed"] = False
    detected_codes = detection["detected_work_codes"]
    if detected_codes:
        rows = [{
            "作业编号": item["code"], "目录匹配": "已匹配" if item["catalog_match_status"] == "matched" else "待人工确认",
            "目录作业类型": "、".join(item["work_types"]) or "—", "来源章节": item["section"] or "未归属章节",
            "来源位置": item["source_locator"] or "未记录", "命中原文": item["source_text"][:160],
        } for item in detected_codes]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("未识别到风险作业目录编号；如方案明确无/不涉及风险作业，可保持为空后确认。")
    st.caption("系统候选类型：" + ("、".join(detection["detected_work_types"]) or "无"))
    confirmed_types = st.multiselect(
        "确认后的涉及作业类型", WORK_TYPE_OPTIONS, key="audit_context_work_types",
        help="输入名称可搜索；可删除误识别类型或补充漏识别类型。",
    )
    unmatched_codes = [item["code"] for item in detected_codes if item["catalog_match_status"] == "unmatched"]
    if unmatched_codes:
        st.warning("未匹配编号：" + "、".join(unmatched_codes))
        st.checkbox("我已人工确认上述未匹配编号的处理方式", key="audit_unmatched_codes_confirmed")
    st.checkbox("我已确认上述作业类型识别结果", key="audit_work_types_confirmed")
    baseline = set(detection["detected_work_types"])
    confirmed = set(confirmed_types)
    return {
        **detection,
        "work_types": list(confirmed_types),
        "confirmed_work_types": list(confirmed_types),
        "work_type_adjustments": {"added": sorted(confirmed - baseline), "removed": sorted(baseline - confirmed)},
        "unmatched_codes_confirmed": bool(st.session_state.get("audit_unmatched_codes_confirmed")),
        "work_types_confirmed": bool(st.session_state.get("audit_work_types_confirmed")),
    }


def _render_result_evidence(evidence: list[dict], image_paths: dict[str, str], prefer_images: bool = False) -> None:
    if not evidence:
        st.info("该结果没有关联到可展示的任务证据。")
        return
    ordered = sorted(evidence, key=lambda item: bool(item.get("image_refs")), reverse=prefer_images)
    for block in ordered:
        block_type = block.get("block_type")
        if block_type == "heading" and block.get("raw_text"):
            st.markdown(f"##### {block['raw_text']}")
        elif block_type == "toc_entry":
            st.info("该内容来自目录，可能不是正文证据。")
            if block.get("raw_text"):
                st.text(block["raw_text"])
        elif block_type == "table":
            payload = block.get("table_json") or {}
            rows = payload.get("rows") if isinstance(payload, dict) else None
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            elif block.get("raw_text"):
                st.text(block["raw_text"])
        elif block.get("raw_text"):
            st.text(block["raw_text"])
        for image_id in block.get("image_refs", []):
            image_path = image_paths.get(image_id)
            if image_path and os.path.isfile(image_path):
                st.image(image_path, width=360)
            else:
                st.warning("图片文件不可用。")
    with st.expander("查看来源位置"):
        for block in ordered:
            section = " / ".join(block.get("section_path") or []) or "未归属章节"
            source = block.get("source_locator") or "未记录"
            st.write(f"章节：{section}；来源：{source}")


def _render_stage2_result_detail(item: dict, image_paths: dict[str, str]) -> None:
    st.markdown("#### 审核项详情")
    summary = st.columns(4)
    summary[0].write(f"**任务 ID**：{item['task_id']}")
    summary[1].write(f"**任务名称**：{item['task_name']}")
    summary[2].write(f"**结果类型**：{dict(RESULT_GROUPS)[item['output_type']]}")
    summary[3].write(f"**状态**：{item.get('result_status') or item.get('execution_status') or '—'}")
    st.write(f"**观察到**：{item.get('summary') or '—'}")
    if item.get("actual_value"):
        st.write(f"**实际值**：{item['actual_value']}")
    if item.get("expected_value"):
        st.write(f"**候选值**：{item['expected_value']}")
    candidates = item.get("candidate_rows") or []
    if candidates:
        total = item.get("candidate_total") or len(candidates)
        st.markdown("#### 风险库缺失危害候选")
        st.caption(f"该步骤共识别 {total} 条候选，当前展示 {len(candidates)} 条。" + ("其余候选未展示。" if item.get("candidate_truncated") else ""))
        st.dataframe(pd.DataFrame([
            {
                "序号": number,
                "候选危害": candidate.get("hazard") or "—",
                "候选控制措施": candidate.get("control_measure") or "—",
                "风险等级": candidate.get("risk_level") or "—",
                "相似度": candidate.get("similarity") or "—",
            }
            for number, candidate in enumerate(candidates, 1)
        ]), use_container_width=True, hide_index=True)
    if item.get("expected"):
        st.write(f"**预期**：{'；'.join(item['expected'])}")
    if item.get("affected_scope"):
        st.write(f"**涉及范围**：{item['affected_scope']}")
    if item.get("suggestion"):
        st.write(f"**处理建议**：{item['suggestion']}")
    if item.get("diagnostics"):
        st.markdown("#### 执行诊断")
        for diagnostic in item["diagnostics"]:
            st.caption(str(diagnostic))
    if item.get("section"):
        st.write(f"**任务预期章节**：{item['section']}")
    if item["output_type"] == "advisories":
        st.info("JSA 提示仅用于辅助识别风险控制关注点，需结合方案原文和现场条件判断。")
    st.markdown("#### 任务证据")
    evidence = item.get("evidence", [])
    evidence_groups = split_evidence(evidence)
    document_evidence = evidence_groups["document"]
    normative_evidence = evidence_groups["normative_clause"]
    graph_evidence = evidence_groups["graph_clue"]
    if document_evidence:
        st.markdown("##### 文档证据")
        _render_result_evidence(document_evidence, image_paths, prefer_images=item["output_type"] == "manual_reviews")
    if normative_evidence:
        st.markdown("##### 规范证据（支持合规结论）")
        for entry in normative_evidence:
            st.info(f"版本：{entry.get('version_id', '未知')}｜条款：{entry.get('clause_id', '未知')}｜发布版：{entry.get('release_id', '未知')}")
            st.write(entry.get("text", ""))
    if graph_evidence:
        st.markdown("##### 图线索（仅工程合理性提示）")
        for entry in graph_evidence:
            st.warning(f"历史案例：{entry.get('source_document_id', '未知')}｜关系断言：{entry.get('assertion_id', '未知')}")
            st.write(entry.get("evidence_sentence") or entry.get("summary", ""))
        st.caption("图线索不能单独支持规范不符合结论。")


def _render_stage2_result_area(report: dict, image_paths: dict[str, str], key_prefix: str) -> None:
    """新建运行和历史回读共用的阶段 2 结果展示区。"""
    st.subheader("阶段 2 审核结果")
    groups = stage2_result_groups(report)
    metrics = st.columns(5)
    for column, (key, label) in zip(metrics, RESULT_GROUPS):
        column.metric(label, len(groups[key]))
    execution_counts = execution_summary(report)
    st.caption("执行状态：" + "｜".join(f"{name} {count}" for name, count in execution_counts.items()))
    export = build_stage2_result_export(report)
    st.download_button(
        "下载阶段 2 审核结果 CSV", export.to_csv(index=False).encode("utf-8-sig"),
        file_name="阶段2审核结果.csv", mime="text/csv", key=f"audit_result_export_{key_prefix}_{report.get('report_metadata', {}).get('report_id', 'current')}",
    )
    pending_count = sum(task.get("execution_status") == "pending" for task in report.get("tasks", []))
    if pending_count:
        st.warning(f"仍有 {pending_count} 项任务尚未执行，不能视为审核通过。")

    labels = dict(RESULT_GROUPS)
    report_key = report.get("report_metadata", {}).get("report_id", "current")
    selected_type = st.selectbox("查看结果类型", [key for key, _ in RESULT_GROUPS], format_func=lambda key: labels[key], key=f"audit_result_type_{key_prefix}_{report_key}")
    entries = groups[selected_type]
    empty_messages = {
        "issues": "未发现需要处理的审核问题。",
        "manual_reviews": "没有待人工核验项。",
        "offline_items": "没有待线下审核项。",
        "advisories": "没有 JSA 提示项。",
        "system_errors": "本次运行没有系统错误。",
    }
    if not entries:
        st.info(empty_messages[selected_type])
        return
    chosen = st.selectbox(
        "选择审核项",
        list(range(len(entries))),
        format_func=lambda index: f"{entries[index]['task_id']}｜{entries[index]['task_name']}｜{entries[index].get('summary') or '—'}",
        key=f"audit_result_item_{key_prefix}_{selected_type}_{report_key}",
    )
    _render_stage2_result_detail(entries[chosen], image_paths)


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
            config = run.get("config") or {}
            rule_set = config.get("deterministic_rule_set") or {}
            jsa_versions = "、".join(config.get("jsa_engine_versions") or []) or "本次未调用"
            st.caption(
                f"任务库：{run.get('task_library_version') or '—'}｜"
                f"规则集：{rule_set.get('id') or '—'} {rule_set.get('version') or '—'}｜"
                f"JSA 引擎：{jsa_versions}"
            )
            report = store.load_latest_draft_report(run_id.strip())
            if report is None:
                st.info("该运行尚未生成阶段 2 审核结果。")
            else:
                versions = store.list_report_versions(run_id.strip())
                st.markdown("#### 报告版本")
                st.dataframe(pd.DataFrame(version_summary(versions)), use_container_width=True, hide_index=True)
                _render_stage2_result_area(report, store.load_document_image_paths(run_id.strip()), "history")
                metadata = report.get("report_metadata", {})
                if metadata.get("status") == "published":
                    with st.expander("创建人工更正版本"):
                        correction_reason = st.text_area("更正原因", key="audit_history_correction_reason")
                        correction_task = st.text_input("更正任务 ID", key="audit_history_correction_task")
                        correction_status = st.selectbox("更正后的结论", ["no_issue", "issue_found", "manual_review"], key="audit_history_correction_status")
                        if st.button("创建新报告版本", key="audit_history_create_correction"):
                            try:
                                corrected = create_correction_version(
                                    report,
                                    changes=[{"task_id": correction_task.strip(), "result_status": correction_status}],
                                    reason=correction_reason.strip(),
                                    source_snapshot=report.get("source_snapshot", {}),
                                )
                                corrected_id = store.save_draft_report(run_id.strip(), corrected, st.session_state.get("audit_context_reviewer", ""))
                                st.success(f"已创建新报告版本，报告 ID：{corrected_id}")
                            except ReportReauditRequired as exc:
                                st.error(str(exc))
                            except (ValueError, RuntimeError) as exc:
                                st.error(f"无法创建更正版本：{exc}")
            with st.expander("查看运行调试信息"):
                st.json(run)
    except Exception as exc:
        st.error(f"读取审核运行失败：{exc}")
    finally:
        store.close()


def _render_human_review_and_publish(report: dict) -> None:
    """Render append-only review actions and the formal-report gate."""
    st.subheader("人工复核与正式发布")
    pending_ids = pending_review_task_ids(report)
    pending = [task for task in report.get("tasks", []) if task.get("task_id") in pending_ids]
    if pending:
        st.warning(f"尚有 {len(pending)} 项人工必办任务未处置；完成前不能发布正式报告。")
    else:
        st.success("人工必办项已全部处置，可以发布正式报告。")
    reviewer = st.text_input("人工复核操作人", key="audit_review_reviewer")
    for task in pending:
        task_id = task.get("task_id", "")
        st.markdown(f"##### {task_id} {task.get('task_name', '')}")
        st.write("；".join(item.get("summary", "") for item in task.get("manual_reviews", [])))
        explanation = st.text_area("处置说明", key=f"audit_review_reason_{task_id}")
        action = st.selectbox("处置动作", ["confirm", "reject", "modify", "supplement"], key=f"audit_review_action_{task_id}")
        if st.button("追加人工处置记录", key=f"audit_review_submit_{task_id}"):
            if not reviewer.strip() or not explanation.strip():
                st.error("请填写操作人和处置说明。")
            else:
                updated = append_review_action(report, task_id=task_id, action=action, reviewer=reviewer.strip(), explanation=explanation.strip())
                if _mysql_enabled() and st.session_state.get("audit_run_id"):
                    review_store = MySQLAuditStore.from_env()
                    try:
                        review_store.append_human_review(
                            execution_id=None, issue_id=None, action_type=action,
                            reviewer_name=reviewer.strip(), reason=explanation.strip(),
                            before_value={"task_id": task_id, "status": "pending"},
                            after_value={"task_id": task_id, "status": "resolved"},
                        )
                    finally:
                        review_store.close()
                st.session_state["audit_stage2_report"] = updated
                st.success("人工处置已追加保存，机器原始结果未覆盖。")
                st.rerun()
    report = st.session_state.get("audit_stage2_report", report)
    if not pending and st.button("发布正式报告", type="primary", key="audit_publish_report"):
        try:
            snapshot = freeze_report_snapshot(report, publisher=reviewer.strip())
            output_dir = AUDIT_STORAGE_DIR / "reports"
            json_path, docx_path = export_report_snapshot(snapshot, output_dir)
            report_id = (report.get("report_metadata") or {}).get("report_id")
            if _mysql_enabled() and report_id:
                publish_store = MySQLAuditStore.from_env()
                try:
                    publish_store.publish_report(report_id, docx_path=str(docx_path))
                finally:
                    publish_store.close()
            st.session_state["audit_published_snapshot"] = snapshot
            st.success(f"报告已发布：{snapshot['publication']['publisher']}；快照 {snapshot['snapshot_sha256'][:16]}…")
            st.download_button("下载正式 JSON", json_path.read_bytes(), file_name=json_path.name, key="audit_download_json")
            st.download_button("下载正式 DOCX", docx_path.read_bytes(), file_name=docx_path.name, key="audit_download_docx")
        except ReportPublishBlocked as exc:
            st.error(str(exc))


def render_audit_page() -> None:
    st.title("施工方案审核")
    st.caption("阶段 1：上传单份 Word、生成证据块、预览任务定位，并由审核员确认审核上下文；阶段 2：执行已接入的确定性规则。")

    capability = doc_conversion_capability()
    if capability.available:
        st.info(f"`.doc` 转换能力：{capability.message}")
    else:
        st.warning(f"`.doc` 转换能力：{capability.message}；`.docx` 仍可正常预览。")

    _render_environment_health()
    _render_run_lookup()
    st.divider()
    st.subheader("新建审核运行")

    configured_provider = os.getenv("LLM_PROVIDER", "zhipu").strip().lower()
    provider_options = list(PROVIDERS)
    if configured_provider not in provider_options:
        configured_provider = provider_options[0]
    provider_id = st.selectbox(
        "审核 LLM provider",
        provider_options,
        index=provider_options.index(configured_provider),
        format_func=lambda value: PROVIDERS[value].label,
        key="audit_context_provider_id",
    )
    provider_preset = PROVIDERS[provider_id]
    provider_base_url = st.text_input(
        "审核 provider Base URL",
        value=(
            os.getenv("LLM_BASE_URL", "")
            if provider_id == "custom"
            else provider_preset.default_base_url
        ) or provider_preset.default_base_url,
        key="audit_context_provider_base_url",
    )
    provider_model = st.text_input(
        "审核模型",
        value=os.getenv("LLM_MODEL", "glm-4.5-air"),
        key="audit_context_provider_model",
    )
    provider_api_key = st.text_input(
        "审核 API Key（仅本次运行覆盖）",
        value="",
        type="password",
        key="audit_context_provider_api_key",
    )
    if resolve_provider_api_key(provider_id, provider_api_key):
        st.caption("已检测到该 provider 的环境凭据；页面不显示密钥内容。")

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
        primary_group = location.evidence_groups[0] if location.evidence_groups else None
        summary = st.columns(4)
        summary[0].write(f"**任务 ID**：{task.task_id}")
        summary[1].write(f"**预期章节**：{task.section}")
        summary[2].write(f"**定位状态**：{location_status_label(location.status)}")
        summary[3].write(f"**系统定位章节**：{group_section_label(primary_group) or '—'}")
        if location.status == "not_located":
            st.info("系统没有找到该任务对应的候选证据。" + (f"\n\n说明：{location.diagnostic}" if location.diagnostic else ""))
        elif not location.evidence_groups:
            st.warning("该任务的定位结果没有可读取的证据组。")
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
                elif block.block_type == "toc_entry":
                    st.info("该内容来自目录，可能不是正文证据。")
                    if block.raw_text:
                        st.text(block.raw_text)
                elif block.block_type == "table":
                    rows = table_rows(block)
                    if rows is None:
                        if block.raw_text:
                            st.text(block.raw_text)
                    else:
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                elif block.raw_text:
                    st.text(block.raw_text)
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
        work_type_context = _render_work_type_confirmation(preview)
        st.markdown("#### 规范审核范围预检")
        recognized_norms = recognize_declared_norms(parsed.blocks)
        confirmed_norms = st.multiselect(
            "自动识别的声明规范候选（请确认）",
            [item.candidate_id for item in recognized_norms],
            format_func=lambda candidate_id: next(item.value for item in recognized_norms if item.candidate_id == candidate_id),
            key="audit_confirmed_norm_candidates",
        )
        if recognized_norms:
            st.caption("候选均保留原文块位置；只有勾选确认的候选进入本次审核上下文。")
        st.text_input("方案声明规范（用逗号分隔）", key="audit_declared_norms", help="只将审核员确认的声明规范纳入本次运行范围。")
        st.text_input("作业类型必备补充规范（用逗号分隔）", key="audit_supplemental_norms", help="补充规范必须由审核员明确登记，不能由模型自动扩展。")
        declared_norms = [item.strip() for item in st.session_state.get("audit_declared_norms", "").split(",") if item.strip()]
        declared_norms.extend(item.value for item in recognized_norms if item.candidate_id in confirmed_norms)
        declared_norms = list(dict.fromkeys(declared_norms))
        supplemental_norms = [item.strip() for item in st.session_state.get("audit_supplemental_norms", "").split(",") if item.strip()]
        if declared_norms or supplemental_norms:
            st.info(f"本次范围：声明规范 {len(declared_norms)} 项，补充规范 {len(supplemental_norms)} 项。版本、索引发布状态和覆盖缺口将在启动前复核。")
        else:
            st.warning("尚未登记规范范围；语义合规任务将无法形成可用规范依据。")
        capability_columns = st.columns(3)
        capability_columns[0].metric("规范检索", "待注入" if not declared_norms else "待预检")
        capability_columns[1].metric("图检索", "按需")
        capability_columns[2].metric("结构化审核", "按运行配置")
        reviewer_name = st.text_input("审核确认人", key="audit_context_reviewer")
        if st.button("确认审核上下文并创建审核运行", type="primary"):
            if not _mysql_enabled():
                st.error("MySQL 持久化未启用，当前不能创建审核运行。")
            else:
                context = {
                    "project_name": st.session_state.get("audit_context_project_name", "").strip(),
                    "audit_year": st.session_state.get("audit_context_year"),
                    "work_purpose": st.session_state.get("audit_context_work_purpose", "").strip(),
                    "declared_norms": declared_norms,
                    "declared_norm_candidates": freeze_confirmed_candidates(recognized_norms, confirmed_norms),
                    "supplemental_norms": supplemental_norms,
                    "llm_provider": provider_id,
                    "llm_base_url": provider_base_url.strip(),
                    "llm_model": provider_model.strip(),
                    "llm_api_key_configured": bool(resolve_provider_api_key(provider_id, provider_api_key)),
                    **(work_type_context or {}),
                }
                try:
                    resolved_key = resolve_provider_api_key(provider_id, provider_api_key)
                    semantic_model = build_structured_model(
                        api_key=resolved_key,
                        base_url=provider_base_url.strip(),
                        model=provider_model.strip(),
                    )
                    try:
                        scope = NormativeScope.freeze(
                            int(context["audit_year"]),
                            context["declared_norms"],
                            context["supplemental_norms"],
                            context.get("confirmed_work_types", ()),
                        )
                        relationship_types = tuple(
                            item.strip() for item in os.getenv(
                                "KG_AUDIT_GRAPH_RELATION_TYPES", "USES,REQUIRES,CONTROLS"
                            ).split(",") if item.strip()
                        )
                        graph_queries = {
                            task.task_id: {
                                "query": task.name,
                                "relationship_types": relationship_types,
                                "max_hops": 2,
                            }
                            for task in preview.task_library.tasks
                            if task.route == "semantic_reasonableness"
                        }
                        composition = ProductionAuditComposition.from_env(
                            model=semantic_model,
                            scope=scope,
                            config_snapshot={
                                "provider": provider_id,
                                "model": provider_model.strip(),
                                "prompt_version": "semantic-audit-v1",
                            },
                            graph_queries=graph_queries,
                        )
                        context.update(composition.as_audit_context())
                    except (ImportError, RuntimeError, ValueError) as exc:
                        context["semantic_runtime"] = None
                        context["semantic_runtime_diagnostic"] = f"生产审核服务不可用：{exc}"
                        st.warning(f"生产审核服务暂不可用，语义任务将记录为未执行：{exc}")
                    context["llm_api_key_configured"] = bool(resolved_key)
                except (ImportError, RuntimeError, ValueError) as exc:
                    context["semantic_runtime"] = None
                    st.warning(f"语义 provider 暂不可用，语义任务将逐项降级：{exc}")
                missing = [name for name, value in {
                    "项目或平台名称": context["project_name"], "作业目的": context["work_purpose"],
                    "审核确认人": reviewer_name.strip(),
                }.items() if not value]
                if work_type_context is None:
                    missing.append("风险作业目录")
                elif not work_type_context["work_types_confirmed"]:
                    missing.append("作业类型识别确认")
                elif any(item["catalog_match_status"] == "unmatched" for item in work_type_context["detected_work_codes"]) and not work_type_context["unmatched_codes_confirmed"]:
                    missing.append("未匹配编号人工确认")
                if missing:
                    st.error("请先填写：" + "、".join(missing))
                    return
                semantic_runtime = context.pop("semantic_runtime", None)
                store = MySQLAuditStore.from_env()
                try:
                    healthy, health_message = store.schema_health()
                    if not healthy:
                        st.error(health_message)
                    else:
                        run_id = store.create_confirmed_run(parsed, preview.task_library, context, reviewer_name.strip())
                        execution_context = dict(context)
                        if semantic_runtime is not None:
                            execution_context["semantic_runtime"] = semantic_runtime
                        results = AuditOrchestrator().execute_preview(preview, execution_context, run_id)
                        store.save_execution_results(run_id, results)
                        report = build_draft_report(preview, results)
                        report_id = store.save_draft_report(run_id, report, reviewer_name.strip())
                        report["report_metadata"] = {"report_id": report_id}
                        st.session_state["audit_run_id"] = run_id
                        st.session_state["audit_stage2_report"] = report
                        st.session_state["audit_stage2_image_paths"] = {
                            image.image_id: str(image.stored_path) for image in parsed.images
                        }
                        completed = sum(result.execution_status == "completed" for result in results)
                        result_groups = stage2_result_groups(report)
                        findings = len(result_groups["issues"]) + len(result_groups["manual_reviews"]) + len(result_groups["offline_items"])
                        pending = sum(result.execution_status == "pending" for result in results)
                        st.success(f"阶段 2 执行完成：已完成 {completed} 项阶段 2 任务；发现 {findings} 项需关注结果；另有 {pending} 项语义审核任务等待后续能力接入。")
                except Exception as exc:
                    st.error(f"创建审核运行失败：{exc}")
                finally:
                    store.close()
    if st.session_state.get("audit_stage2_report"):
        st.divider()
        _render_stage2_result_area(
            st.session_state["audit_stage2_report"],
            st.session_state.get("audit_stage2_image_paths", {}),
            "current",
        )
        _render_human_review_and_publish(st.session_state["audit_stage2_report"])
