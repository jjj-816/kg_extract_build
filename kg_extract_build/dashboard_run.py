"""Run-experiment page with live progress monitoring."""

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from kg_extract_build.documents import discover_documents
from kg_extract_build.pipeline import run_pipeline
from kg_extract_build.run_config import (
    ChunkingConfig,
    LLMConfig,
    PipelineConfig,
    PROVIDERS,
    resolve_provider_api_key,
)
from kg_extract_build.runtime import PipelineRunRegistry, reduce_events


# ---------------------------------------------------------------------------
# Pure helpers – testable without a Streamlit server
# ---------------------------------------------------------------------------


def chunking_notice(max_chars):
    if int(max_chars) == 2000:
        return (
            "info",
            "当前使用项目默认切片配置：Markdown 标题感知，最大长度 2000 字符",
        )
    return (
        "warning",
        f"当前已调整切片长度，本次实验将使用自定义配置：最大长度 {int(max_chars)} 字符",
    )


def relation_strategy_notice(strategy):
    if strategy == "single_entity":
        return "当前使用逐实体关系抽取基线：每个实体单独调用 LLM。"
    return (
        "当前使用共享上下文批量抽取：仅合并具有共同证据的实体，"
        "无关实体仍单独处理。"
    )


def thinking_mode_notice(enabled):
    if enabled:
        return (
            "已启用思考模式：可能提升复杂任务效果，"
            "但会增加响应时间和推理 Token 消耗。"
        )
    return "默认关闭思考模式，以减少响应时间和推理 Token 消耗。"


def build_llm_config(
    provider_id,
    api_key,
    base_url,
    model,
    enable_thinking=False,
):
    return LLMConfig(
        provider_id=provider_id,
        api_key=api_key,
        base_url=base_url,
        model=model,
        enable_thinking=bool(enable_thinking),
    )


def provider_form_defaults(provider_id):
    preset = PROVIDERS[provider_id]
    return {
        "label": preset.label,
        "base_url": preset.default_base_url,
        "requires_api_key": preset.requires_api_key,
        "environment_configured": bool(
            resolve_provider_api_key(provider_id)
        ),
    }


def default_run_name(now=None):
    now = now or datetime.now()
    return now.strftime("kg-run-%Y%m%d-%H%M%S")


# ---------------------------------------------------------------------------
# Run registry – survives Streamlit reruns
# ---------------------------------------------------------------------------


@st.cache_resource
def get_run_registry():
    return PipelineRunRegistry(run_pipeline)


# ---------------------------------------------------------------------------
# Monitor body – pure event-to-UI rendering
# ---------------------------------------------------------------------------


PIPELINE_STAGE_LABELS = [('document', '文档'), ('preprocessing', '预处理'), ('chunking', '切片'), ('entity_extraction', '实体抽取'), ('entity_alignment', '实体对齐'), ('retrieval', '语义检索'), ('triplet_extraction', '三元组生成'), ('triplet_correction', '校正'), ('completed', '完成')]

def render_monitor_body(registry):
    events = registry.drain_events()
    state = reduce_events(
        st.session_state.get("pipeline_view_state", {}), events
    )
    st.session_state["pipeline_view_state"] = state

    metrics = state.get("metrics", {})
    columns = st.columns(5)
    columns[0].metric("文档", metrics.get("documents", 0))
    columns[1].metric("切片", metrics.get("chunks", 0))
    columns[2].metric("实体", metrics.get("entities", 0))
    columns[3].metric("LLM 调用", metrics.get("llm_calls", 0))
    columns[4].metric("三元组", metrics.get("triplets", 0))

    completed = state.get("document_completed") or 0
    total = state.get("document_total") or 0
    st.progress(
        completed / total if total else 0.0,
        text=f"文档进度：{completed}/{total}",
    )
    st.write(f"当前阶段：{state.get('stage', '等待开始')}")
    st.write(f"当前文档：{state.get('document_name') or '—'}")

    stage_labels = PIPELINE_STAGE_LABELS
    seen_stages = set(state.get("seen_stages", []))
    st.caption(
        " → ".join(
            f"{'✅' if stage in seen_stages else '○'} {label}"
            for stage, label in stage_labels
        )
    )

    status = state.get("status", "idle")
    status_renderers = {
        "running": (st.info, "实验正在运行"),
        "completed": (st.success, "实验运行完成"),
        "completed_with_errors": (st.warning, "实验完成，但部分文档失败"),
        "cancelled": (st.warning, "实验已安全停止"),
        "failed": (st.error, "实验运行失败"),
    }
    if status in status_renderers:
        renderer, text = status_renderers[status]
        renderer(text)

    for event in reversed(state.get("events", [])[-50:]):
        st.caption(f"{event.timestamp} · {event.message}")

    if state.get("run_id") is not None:
        st.success(f"实验 run_id：{state['run_id']}")
        if st.button(
            "查看本次实验", key=f"inspect_run_{state['run_id']}"
        ):
            st.session_state["preferred_run_id"] = state["run_id"]
            st.session_state["requested_navigation_page"] = "实验批次"
            st.rerun(scope="app")

    return bool(events)


@st.fragment(run_every=1.0)
def render_active_monitor(registry):
    had_events = render_monitor_body(registry)
    if not registry.is_running and had_events:
        st.rerun(scope="app")


# ---------------------------------------------------------------------------
# Main run page
# ---------------------------------------------------------------------------


def render_run_page():
    st.markdown(
        '<div class="kg-eyebrow">KG Experiment Console</div>',
        unsafe_allow_html=True,
    )
    st.title("运行实体提取实验")
    st.caption(
        "配置本次实验并实时查看切片、实体、检索和三元组生成过程。"
    )

    config_col, monitor_col = st.columns([0.36, 0.64], gap="large")
    registry = get_run_registry()

    # -- left: configuration ------------------------------------------------
    with config_col:
        if "experiment_run_name" not in st.session_state:
            st.session_state["experiment_run_name"] = default_run_name()
        run_name = st.text_input(
            "实验名称",
            key="experiment_run_name",
            disabled=registry.is_running,
        )
        folder_text = st.text_input(
            "本机文档文件夹",
            value=os.getenv("KG_DOCUMENT_FOLDER", ""),
            disabled=registry.is_running,
        )

        documents = []
        if folder_text.strip():
            try:
                documents = discover_documents(Path(folder_text))
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "文件名": item.name,
                                "类型": item.extension,
                                "大小（字节）": item.size_bytes,
                            }
                            for item in documents
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
            except ValueError as exc:
                st.warning(str(exc))

        selected_files = st.multiselect(
            "选择本次处理的文件",
            [item.name for item in documents],
            default=[item.name for item in documents],
            disabled=registry.is_running,
        )

        provider_id = st.selectbox(
            "LLM 提供商",
            list(PROVIDERS),
            format_func=lambda value: PROVIDERS[value].label,
            disabled=registry.is_running,
        )
        preset = provider_form_defaults(provider_id)
        base_url = st.text_input(
            "Base URL",
            value=preset["base_url"],
            key=f"llm_base_url_{provider_id}",
            disabled=registry.is_running,
        )
        model = st.text_input(
            "模型名称",
            value=os.getenv("LLM_MODEL", ""),
            key=f"llm_model_{provider_id}",
            disabled=registry.is_running,
        )
        api_key_override = st.text_input(
            "API Key（仅本次会话临时覆盖）",
            value="",
            type="password",
            key=f"llm_api_key_{provider_id}",
            disabled=registry.is_running,
        )
        if preset["environment_configured"]:
            st.caption("已从对应环境变量读取凭据；临时输入将优先使用。")

        enable_thinking = st.checkbox(
            "启用思考模式",
            value=False,
            disabled=registry.is_running,
        )
        st.caption(thinking_mode_notice(enable_thinking))

        max_chars = st.number_input(
            "切片最大长度（字符）",
            min_value=200,
            max_value=20000,
            value=2000,
            step=100,
            disabled=registry.is_running,
        )
        notice_level, notice_text = chunking_notice(max_chars)
        getattr(st, notice_level)(notice_text)

        with st.expander("高级参数"):
            retrieve_count = st.number_input(
                "每个实体检索句数",
                min_value=1,
                max_value=100,
                value=10,
                disabled=registry.is_running,
            )
            relation_strategy = st.selectbox(
                "关系抽取策略",
                options=(
                    "shared_context_batch",
                    "single_entity",
                ),
                format_func=lambda value: (
                    "共享上下文批量抽取（推荐）"
                    if value == "shared_context_batch"
                    else "逐实体抽取（论文基线）"
                ),
                disabled=registry.is_running,
            )
            st.caption(relation_strategy_notice(relation_strategy))
            if relation_strategy == "shared_context_batch":
                relation_batch_max_entities = st.number_input(
                    "每个关系批次最多实体数",
                    min_value=1,
                    max_value=10,
                    value=3,
                    step=1,
                    disabled=registry.is_running,
                )
                relation_batch_min_overlap = st.slider(
                    "实体检索证据最小重叠系数",
                    min_value=0.0,
                    max_value=1.0,
                    value=0.4,
                    step=0.05,
                    disabled=registry.is_running,
                )
                relation_batch_max_context_chars = st.number_input(
                    "每个关系批次最大上下文字符数",
                    min_value=1000,
                    max_value=50000,
                    value=8000,
                    step=500,
                    disabled=registry.is_running,
                )
            else:
                relation_batch_max_entities = 3
                relation_batch_min_overlap = 0.4
                relation_batch_max_context_chars = 8000
            respect_breakpoint = st.checkbox(
                "跳过断点记录中的已处理文件",
                value=False,
                disabled=registry.is_running,
            )
            reuse_entity_cache = st.checkbox(
                "复用实体对齐缓存",
                value=False,
                disabled=registry.is_running,
            )
            reuse_triplet_cache = st.checkbox(
                "复用三元组缓存",
                value=False,
                disabled=registry.is_running,
            )

        start_col, stop_col = st.columns(2)
        with start_col:
            start_clicked = st.button(
                "开始运行",
                type="primary",
                use_container_width=True,
                disabled=registry.is_running,
            )
        with stop_col:
            stop_clicked = st.button(
                "停止实验",
                use_container_width=True,
                disabled=not registry.is_running,
            )
        if stop_clicked:
            registry.request_cancel()
            st.warning("已请求停止，将在当前请求结束后的安全边界停止。")

        if start_clicked:
            try:
                api_key = resolve_provider_api_key(
                    provider_id, api_key_override
                )
                config = PipelineConfig(
                    run_name=run_name.strip(),
                    document_folder=Path(folder_text),
                    selected_files=tuple(selected_files),
                    llm=build_llm_config(
                        provider_id=provider_id,
                        api_key=api_key,
                        base_url=base_url.strip(),
                        model=model.strip(),
                        enable_thinking=enable_thinking,
                    ),
                    chunking=ChunkingConfig(max_chars=int(max_chars)),
                    retrieve_sentence_num=int(retrieve_count),
                    respect_legacy_breakpoint=respect_breakpoint,
                    reuse_entity_cache=reuse_entity_cache,
                    reuse_triplet_cache=reuse_triplet_cache,
                    relation_strategy=relation_strategy,
                    relation_batch_max_entities=int(
                        relation_batch_max_entities
                    ),
                    relation_batch_min_overlap=float(
                        relation_batch_min_overlap
                    ),
                    relation_batch_max_context_chars=int(
                        relation_batch_max_context_chars
                    ),
                )
                config.validate()
                registry.start(config)
                st.session_state["pipeline_view_state"] = {}
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))

    # -- right: monitor ----------------------------------------------------
    with monitor_col:
        if registry.is_running:
            render_active_monitor(registry)
        else:
            render_monitor_body(registry)
