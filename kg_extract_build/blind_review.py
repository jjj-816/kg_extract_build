from __future__ import annotations

import csv
import io
import zipfile


def _csv_text(rows: list[dict[str, object]], fields: list[str]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _group_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    documents = {
        str(row["file_name"])
        for row in records
    }
    document_codes = {
        name: f"DOC-{index:03d}"
        for index, name in enumerate(sorted(documents), start=1)
    }
    grouped: dict[int, dict[str, object]] = {}
    for row in records:
        triplet_id = int(row["triplet_id"])
        item = grouped.setdefault(
            triplet_id,
            {
                "document_code": document_codes[str(row["file_name"])],
                "head": row["head"],
                "head_type": row["head_type"],
                "relation": row["relation_name"],
                "tail": row["tail"],
                "tail_type": row["tail_type"],
                "evidence": [],
                "contexts": [],
            },
        )
        sentence = str(row.get("evidence_sentence") or "").strip()
        context = str(row.get("evidence_context") or "").strip()
        if sentence and sentence not in item["evidence"]:
            item["evidence"].append(sentence)
        if context and context not in item["contexts"]:
            item["contexts"].append(context)

    samples = []
    for index, item in enumerate(grouped.values(), start=1):
        item["sample_id"] = f"BR-{index:04d}"
        item["evidence_text"] = "\n".join(
            f"[{number}] {sentence}"
            for number, sentence in enumerate(item.pop("evidence"), start=1)
        ) or "（该三元组未保存模型选定证据）"
        item["context_text"] = "\n\n".join(item.pop("contexts")) or "（无可用上下文）"
        samples.append(item)
    return samples


def build_blind_review_package(records: list[dict[str, object]]) -> tuple[bytes, int]:
    """Build an expert-facing ZIP without method, Gold, or internal identifiers."""
    samples = _group_records(records)
    form_fields = [
        "sample_id", "document_code", "head", "head_type", "relation", "tail",
        "tail_type", "evidence_text", "fact_correctness",
        "canonicalization_correctness", "relation_direction",
        "evidence_sufficiency", "final_decision", "error_type", "comment",
    ]
    form_rows = [
        {
            "sample_id": item["sample_id"],
            "document_code": item["document_code"],
            "head": item["head"],
            "head_type": item["head_type"],
            "relation": item["relation"],
            "tail": item["tail"],
            "tail_type": item["tail_type"],
            "evidence_text": item["evidence_text"],
            "fact_correctness": "",
            "canonicalization_correctness": "",
            "relation_direction": "",
            "evidence_sufficiency": "",
            "final_decision": "",
            "error_type": "",
            "comment": "",
        }
        for item in samples
    ]
    context_rows = [
        {
            "sample_id": item["sample_id"],
            "document_code": item["document_code"],
            "evidence_text": item["evidence_text"],
            "context_text": item["context_text"],
        }
        for item in samples
    ]
    readme = """# 单实验盲审说明

本包不包含实验名称、方法名称、模型、检索分数、Gold 答案或内部数据库编号。

请基于预测三元组、系统选定证据及上下文独立填写 `blind_review_form.csv`：

- `fact_correctness`：正确 / 部分正确 / 错误；
- `canonicalization_correctness`：正确 / 部分正确 / 错误 / 不适用；
- `relation_direction`：正确 / 反向 / 不适用；
- `evidence_sufficiency`：充分 / 不足 / 无关；
- `final_decision`：仅“事实正确且证据充分”填写接受；其余填写部分接受或拒绝；
- `error_type`：实体边界错误、实体类型错误、规范化错误、关系类型错误、方向错误、尾实体错误、数值/单位错误、证据不足、无关证据、其他。

不得根据系统外部信息推断方法来源；存在分歧时保留备注，交由后续裁决。
"""
    markdown_parts = ["# 单实验盲审样本\n"]
    for item in samples:
        markdown_parts.extend([
            f"## {item['sample_id']}（{item['document_code']}）",
            f"预测三元组：{item['head']}（{item['head_type']}） — {item['relation']} → {item['tail']}（{item['tail_type']}）",
            "\n### 系统选定证据\n",
            item["evidence_text"],
            "\n### 证据上下文\n",
            item["context_text"],
            "\n---\n",
        ])
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("README_盲审说明.md", readme.encode("utf-8"))
        package.writestr(
            "blind_review_form.csv",
            _csv_text(form_rows, form_fields).encode("utf-8-sig"),
        )
        package.writestr(
            "evidence_contexts.csv",
            _csv_text(
                context_rows,
                ["sample_id", "document_code", "evidence_text", "context_text"],
            ).encode("utf-8-sig"),
        )
        package.writestr(
            "blind_review_samples.md",
            "\n".join(markdown_parts).encode("utf-8"),
        )
    return archive.getvalue(), len(samples)
