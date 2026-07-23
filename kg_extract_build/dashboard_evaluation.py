from __future__ import annotations
import csv
import io

from pathlib import Path

import streamlit as st

from .blind_review import build_blind_review_package
from .experiment_export import build_experiment_package
from .evaluation import (
    build_preview,
    compute_gold_hash,
    evaluate_documents,
    load_gold_annotations,
)
from .persistence import MySQLExperimentStore
from .schema import KGSchema
from .settings import resolve_schema_path


def format_run_label(row: dict) -> str:
    run_id = str(row.get("run_id", ""))
    run_name = str(row.get("run_name") or "未命名实验")
    status = str(row.get("status") or "unknown")
    started_at = str(row.get("started_at") or "")
    return f"{run_name} | {status} | {started_at} | {run_id[:8]}"


def _triplet_count(triplets_by_doc: dict[str, list[tuple]]) -> int:
    return sum(len(items) for items in triplets_by_doc.values())


def _metric_value(overall: dict, name: str) -> float:
    metric = overall.get(name)
    return 0.0 if metric is None else float(metric.value)


def _render_metric_cards(overall: dict) -> None:
    cols = st.columns(7)
    names = [
        "entity_f1",
        "relation_f1",
        "triplet_f1",
        "canonical_triplet_f1",
        "invalid_relation_rate",
        "selected_evidence_tail_absence_rate",
        "selected_evidence_coverage",
    ]
    labels = [
        "Entity F1",
        "Relation F1",
        "Triplet F1",
        "规范化 Triplet F1（主指标）",
        "非法关系率",
        "疑似无支持率",
        "证据覆盖率",
    ]
    for col, name, label in zip(cols, names, labels):
        col.metric(label, f"{_metric_value(overall, name):.3f}")


def _render_nonempty_head_cards(overall: dict) -> None:
    cols = st.columns(6)
    names = [
        "nonempty_head_entity_rate",
        "nonempty_head_entity_f1",
        "nonempty_head_canonical_entity_f1",
        "nonempty_head_triplet_f1",
        "nonempty_head_canonical_triplet_f1",
        "empty_head_entity_rate",
    ]
    labels = [
        "非空头实体占比",
        "非空头实体严格 Entity F1",
        "非空头实体规范化 Entity F1",
        "非空头实体严格 Triplet F1",
        "非空头实体规范化 Triplet F1",
        "空三元组头实体占比",
    ]
    for col, name, label in zip(cols, names, labels):
        col.metric(label, f"{_metric_value(overall, name):.3f}")


def _render_canonical_entity_cards(overall: dict) -> None:
    st.caption("全局规范化实体质量：对最终三元组的全部头、尾实体进行评估阶段映射；适用于所有实验方法。")
    cols = st.columns(3)
    names = [
        "canonical_entity_precision",
        "canonical_entity_recall",
        "canonical_entity_f1",
    ]
    labels = [
        "规范化实体 Precision",
        "规范化实体 Recall",
        "规范化实体 F1",
    ]
    for col, name, label in zip(cols, names, labels):
        col.metric(label, f"{_metric_value(overall, name):.3f}")


def _metric_label_and_description(name: str) -> tuple[str, str]:
    contexts = {
        "entity": ("\u5b9e\u4f53", "\u9884\u6d4b\u5b9e\u4f53\u4e0e Gold \u5b9e\u4f53\u7684\u5339\u914d\u8d28\u91cf"),
        "relation": ("\u5173\u7cfb", "\u9884\u6d4b\u5173\u7cfb\u4e0e Gold \u5173\u7cfb\u7684\u5339\u914d\u8d28\u91cf"),
        "triplet": ("\u4e25\u683c\u4e09\u5143\u7ec4", "\u6309\u539f\u59cb\u5934\u3001\u5173\u7cfb\u3001\u5c3e\u548c\u7c7b\u578b\u5b8c\u5168\u5339\u914d\u7684\u4e09\u5143\u7ec4\u8d28\u91cf"),
        "canonical_triplet": ("\u89c4\u8303\u5316\u4e09\u5143\u7ec4", "\u6309 head_id\u3001\u5173\u7cfb\u3001tail_id \u5339\u914d\u7684\u4e3b\u8bc4\u4ef7\u4e09\u5143\u7ec4\u8d28\u91cf"),
        "nonempty_head_entity": ("\u975e\u7a7a\u5934\u5b9e\u4f53", "\u4ec5\u5bf9\u6700\u7ec8\u4ea7\u51fa\u4e86\u4e09\u5143\u7ec4\u7684\u5934\u5b9e\u4f53\u8bc4\u4ef7\u62bd\u53d6\u8d28\u91cf"),
        "nonempty_head_canonical_entity": ("\u975e\u7a7a\u5934\u5b9e\u4f53\u89c4\u8303\u5316", "\u4ec5\u5bf9\u975e\u7a7a\u5934\u5b9e\u4f53\u6309 canonical ID \u8bc4\u4ef7\u5b9e\u4f53\u5f52\u4e00\u8d28\u91cf"),
        "nonempty_head_triplet": ("\u975e\u7a7a\u5934\u4e25\u683c\u4e09\u5143\u7ec4", "\u4ec5\u5bf9\u975e\u7a7a\u5934\u5b9e\u4f53\u7684\u4e25\u683c\u4e09\u5143\u7ec4\u8d28\u91cf"),
        "nonempty_head_canonical_triplet": ("\u975e\u7a7a\u5934\u89c4\u8303\u5316\u4e09\u5143\u7ec4", "\u4ec5\u5bf9\u975e\u7a7a\u5934\u5b9e\u4f53\u7684\u89c4\u8303\u5316\u4e09\u5143\u7ec4\u8d28\u91cf"),
    }
    suffixes = {
        "precision": ("\u7cbe\u786e\u7387", "\u9884\u6d4b\u7ed3\u679c\u4e2d\u6b63\u786e\u9879\u7684\u6bd4\u4f8b"),
        "recall": ("\u53ec\u56de\u7387", "Gold \u4e2d\u6b63\u786e\u9879\u88ab\u627e\u56de\u7684\u6bd4\u4f8b"),
        "f1": ("F1\u503c", "\u7cbe\u786e\u7387\u4e0e\u53ec\u56de\u7387\u7684\u8c03\u548c\u5e73\u5747"),
    }
    for prefix, (label, description) in contexts.items():
        for suffix, (suffix_label, suffix_description) in suffixes.items():
            if name == f"{prefix}_{suffix}":
                return f"{label}{suffix_label}", f"{description}\uff1b{suffix_description}"
    special = {
        "canonical_entity_precision": ("规范化实体精确率", "最终三元组的全部头、尾实体映射到 Gold canonical ID 后，预测实体中正确项的比例"),
        "canonical_entity_recall": ("规范化实体召回率", "最终三元组的全部头、尾实体映射到 Gold canonical ID 后，Gold 实体被找回的比例"),
        "canonical_entity_f1": ("规范化实体F1值", "最终三元组的全部头、尾实体映射到 Gold canonical ID 后的精确率与召回率调和平均"),
        "invalid_relation_rate": ("\u975e\u6cd5\u5173\u7cfb\u7387", "\u4e0d\u7b26\u5408 Schema \u5934\u5c3e\u7c7b\u578b\u7ea6\u675f\u7684\u9884\u6d4b\u5173\u7cfb\u6bd4\u4f8b"),
        "selected_evidence_coverage": ("\u9009\u5b9a\u8bc1\u636e\u8986\u76d6\u7387", "\u5df2\u7ed1\u5b9a\u6a21\u578b\u9009\u5b9a\u8bc1\u636e\u53e5\u7684\u4e09\u5143\u7ec4\u6bd4\u4f8b"),
        "selected_evidence_tail_absence_rate": ("\u9009\u5b9a\u8bc1\u636e\u5c3e\u5b9e\u4f53\u7f3a\u5931\u7387", "\u6a21\u578b\u9009\u5b9a\u7684\u8bc1\u636e\u53e5\u4e2d\u672a\u51fa\u73b0\u5c3e\u5b9e\u4f53\u7684\u4e09\u5143\u7ec4\u6bd4\u4f8b"),
        "canonical_entity_mapping_rate": ("\u5b9e\u4f53\u89c4\u8303\u5316\u6620\u5c04\u7387", "\u9884\u6d4b\u5b9e\u4f53\u88ab\u552f\u4e00\u6620\u5c04\u5230 Gold canonical ID \u7684\u6bd4\u4f8b"),
        "nonempty_head_entity_rate": ("\u975e\u7a7a\u5934\u5b9e\u4f53\u5360\u6bd4", "\u5bf9\u9f50\u540e\u5934\u5b9e\u4f53\u4e2d\u6700\u7ec8\u4ea7\u51fa\u81f3\u5c11\u4e00\u6761\u4e09\u5143\u7ec4\u7684\u6bd4\u4f8b"),
        "empty_head_entity_rate": ("\u7a7a\u5934\u5b9e\u4f53\u5360\u6bd4", "\u5bf9\u9f50\u540e\u5934\u5b9e\u4f53\u4e2d\u6700\u7ec8\u6ca1\u6709\u4ea7\u51fa\u4e09\u5143\u7ec4\u7684\u6bd4\u4f8b"),
        "output_head_outside_aligned_rate": ("\u5934\u5b9e\u4f53\u8d85\u51fa\u5bf9\u9f50\u96c6\u6bd4\u4f8b", "\u6700\u7ec8\u4e09\u5143\u7ec4\u5934\u5b9e\u4f53\u4e0d\u5728\u5bf9\u9f50\u5b9e\u4f53\u96c6\u4e2d\u7684\u6bd4\u4f8b"),
    }
    return special.get(name, (name, "\u672a\u914d\u7f6e\u4e13\u95e8\u8bf4\u660e\u7684\u8bc4\u4f30\u6307\u6807"))


def _metric_row(name, value, numerator, denominator):
    label, description = _metric_label_and_description(name)
    return {
        "\u539f\u59cb\u5b57\u6bb5": name,
        "\u4e2d\u6587\u6307\u6807": label,
        "\u6307\u6807\u8bf4\u660e": description,
        "\u6570\u503c": value,
        "\u5206\u5b50\uff08\u6b63\u786e\u6570\uff09": numerator,
        "\u5206\u6bcd\uff08\u603b\u6570\uff09": denominator,
    }


def _summary_rows(overall: dict) -> list[dict[str, object]]:
    return [
        _metric_row(name, metric.value, metric.numerator, metric.denominator)
        for name, metric in overall.items()
    ]


def _document_rows(by_document: dict) -> list[dict[str, object]]:
    rows = []
    for doc_name, metrics in by_document.items():
        row = {"document": doc_name}
        row.update({name: metric.value for name, metric in metrics.items()})
        rows.append(row)
    return rows

def _csv_bytes(rows: list[dict[str, object]]) -> bytes:
    if not rows:
        return b""
    fields = list(rows[0])
    for row in rows[1:]:
        for field in row:
            if field not in fields:
                fields.append(field)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")



def render_evaluation_page() -> None:
    st.title("实验评估")
    st.caption("选择历史实验和人工标注三元组文件夹，计算实体、关系、三元组和证据质量指标。")

    try:
        store = MySQLExperimentStore.from_env()
        store.initialize_schema()
        runs = store.list_experiment_runs(limit=100)
    except Exception as exc:
        st.warning(f"无法连接 MySQL 或读取实验记录：{exc}")
        st.info("请确认已配置 MySQL，并执行过 kg_extract_build/schema.sql 初始化表结构。")
        return

    if not runs:
        st.info("当前没有可评估的历史实验记录。")
        return

    selected = st.selectbox("选择历史实验", runs, format_func=format_run_label)
    run_id = selected["run_id"]
    export_package, export_counts = build_experiment_package(
        store.load_experiment_export(run_id)
    )
    st.download_button(
        "下载单实验完整数据包 ZIP",
        data=export_package,
        file_name=f"experiment-data-{str(run_id)[:8]}.zip",
        mime="application/zip",
        help=(
            "含运行配置、文档、实体、检索、LLM 调用、原始/最终三元组、"
            f"证据关联和评估结果；最终三元组 {export_counts['final_triplets']} 条。"
        ),
    )
    blind_records = store.load_blind_review_records(run_id)
    if blind_records:
        blind_package, blind_sample_count = build_blind_review_package(blind_records)
        st.download_button(
            "下载单实验盲审证据包 ZIP",
            data=blind_package,
            file_name="blind-review-evidence-package.zip",
            mime="application/zip",
            help=(
                f"共 {blind_sample_count} 条匿名三元组样本；包内不包含实验、模型、"
                "Gold 或内部数据库标识。"
            ),
        )
    else:
        st.info("当前实验没有可导出的 final 三元组盲审样本。")
    gold_path_text = st.text_input("人工标注文件夹路径", value="")
    if not gold_path_text.strip():
        st.info("请输入人工标注文件夹路径后预览匹配情况。")
        return

    gold_path = Path(gold_path_text).expanduser()
    schema = KGSchema(resolve_schema_path())
    gold = load_gold_annotations(gold_path, schema=schema)
    gold_hash = compute_gold_hash(gold_path)
    evaluation_input = store.load_evaluation_input(run_id)
    model_triplets = evaluation_input["triplets"]
    model_documents = set(evaluation_input["documents"].keys())
    existing = store.list_evaluations(run_id, gold_hash=gold_hash)
    evaluation_signature = (run_id, gold_hash)
    preview = build_preview(
        model_documents=model_documents,
        gold=gold,
        model_triplet_count=_triplet_count(model_triplets),
        existing_evaluations=existing,
    )

    st.subheader("预览匹配情况")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("历史实验文档", preview["model_document_count"])
    c2.metric("标注文档", preview["gold_document_count"])
    c3.metric("成功匹配", preview["matched_document_count"])
    c4.metric("已有评估", preview["existing_evaluation_count"])
    st.write(
        {
            "gold_hash": gold_hash,
            "gold_triplet_count": preview["gold_triplet_count"],
            "model_triplet_count": preview["model_triplet_count"],
        }
    )

    if preview["missing_gold_documents"]:
        st.warning(
            "缺失标注的实验文档："
            + ", ".join(preview["missing_gold_documents"])
        )
    if preview["extra_gold_documents"]:
        st.info(
            "标注中多出的文档："
            + ", ".join(preview["extra_gold_documents"])
        )
    if preview["parse_errors"]:
        st.error("部分标注文件解析失败")
        st.dataframe(preview["parse_errors"], use_container_width=True)
    if existing:
        st.info("检测到该实验和当前标注内容已经评估过，可查看已有结果，也可以重新计算并保存为新记录。")
        saved_evaluation = st.selectbox(
            "\u67e5\u770b\u5df2\u4fdd\u5b58\u7684\u8bc4\u4f30\u7ed3\u679c", existing, key="saved_evaluation",
            format_func=lambda row: f"{row.get('created_at')} | {str(row.get('evaluation_id', ''))[:8]}",
        )
        saved_report = store.load_evaluation_report(saved_evaluation["evaluation_id"])
        overall_rows = [
            _metric_row(
                row["metric_name"],
                row["metric_value"],
                row.get("numerator"),
                row.get("denominator"),
            )
            for row in saved_report["metrics"]
            if row["scope_type"] == "overall"
        ]
        st.subheader("\u5df2\u4fdd\u5b58\u7684\u8bc4\u4f30\u6307\u6807")
        st.dataframe(overall_rows, use_container_width=True, hide_index=True)
        st.download_button(
            "\u5bfc\u51fa\u5df2\u4fdd\u5b58\u8bc4\u4f30\u6307\u6807 CSV",
            data=_csv_bytes(overall_rows),
            file_name=f"evaluation-metrics-{saved_evaluation['evaluation_id']}.csv",
            mime="text/csv",
        )


    if preview["calculation_blocked"]:
        st.error("Gold parsing or document matching is incomplete; metric calculation is disabled.")

    if st.button("计算指标", type="primary", disabled=preview["calculation_blocked"]):
        documents_text = {
            name: item["content"]
            for name, item in evaluation_input["documents"].items()
        }
        result = evaluate_documents(
            model=model_triplets,
            gold=gold.documents,
            documents=documents_text,
            evidence=evaluation_input.get("evidence", {}),
            schema=schema,
            canonical_entities=gold.canonical_entities,
            canonical_gold_triplets=gold.canonical_triplets,
            head_entities=evaluation_input.get("head_entities", {}),
        )
        st.session_state["evaluation_result"] = result
        st.session_state["evaluation_gold_hash"] = gold_hash
        st.session_state["evaluation_gold_path"] = str(gold_path)
        st.session_state["evaluation_run_id"] = run_id
        st.session_state["evaluation_signature"] = evaluation_signature

    result = st.session_state.get("evaluation_result")
    if result is not None and st.session_state.get("evaluation_signature") != evaluation_signature:
        st.session_state.pop("evaluation_result", None)
        result = None
        st.info("实验或 Gold 已变更，请重新计算指标后再保存。")
    if result is None:
        return

    st.subheader("评估结果")
    _render_metric_cards(result.overall)
    _render_canonical_entity_cards(result.overall)
    st.subheader("非空头实体条件下的三元组抽取质量")
    st.caption("仅评价实体对齐后、最终产出至少一条三元组的头实体；全量指标仍保留在上方。")
    _render_nonempty_head_cards(result.overall)
    st.dataframe(_summary_rows(result.overall), use_container_width=True)
    document_rows = _document_rows(result.by_document)
    if document_rows:
        st.subheader("按文档指标")
        st.dataframe(document_rows, use_container_width=True)
    if result.entity_alignments:
        st.subheader("预测实体规范化对齐明细")
        st.caption("仅唯一匹配的 Gold canonical ID 可进入规范化三元组主指标。")
        st.dataframe(result.entity_alignments, use_container_width=True)

    if st.button("保存评估结果"):
        evaluation_id = store.save_evaluation(
            run_id=st.session_state["evaluation_run_id"],
            gold_path=st.session_state["evaluation_gold_path"],
            gold_hash=st.session_state["evaluation_gold_hash"],
            metric_config={
                "matching": ["strict", "canonical_id"],
                "gold_hash": st.session_state["evaluation_gold_hash"],
            },
            result=result,
        )
        st.success(f"评估结果已保存：{evaluation_id}")
