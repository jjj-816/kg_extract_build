"""Build a complete, reproducible single-experiment export package."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, datetime
from typing import Mapping, Sequence


EXPORT_LAYOUT = (
    ("documents", "01_文档.csv"),
    ("chunks", "02_切片.csv"),
    ("entities", "03_实体.csv"),
    ("retrieval_results", "04_检索结果.csv"),
    ("llm_calls", "05_LLM调用记录.csv"),
    ("raw_triplets", "06_原始三元组.csv"),
    ("final_triplets", "07_最终三元组.csv"),
    ("triplet_evidence", "08_三元组证据关联.csv"),
    ("evaluations", "09_评估记录.csv"),
    ("evaluation_metrics", "10_评估指标.csv"),
    ("evaluation_alignments", "11_实体对齐明细.csv"),
)


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ")
    return value


def _csv_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    fields = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    buffer = io.StringIO(newline="")
    if fields:
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(
            {field: _cell(value) for field, value in row.items()}
            for row in rows
        )
    return buffer.getvalue().encode("utf-8-sig")


def _readme(run: Mapping[str, object]) -> str:
    return f"""# 单实验完整数据包

本压缩包导出实验运行 `{run.get('run_id', '')}` 的可复现实验数据。

## 内容

- `00_运行信息.json`：实验名称、状态、代码提交版本、运行配置快照与 Schema 快照。
- `01` 至 `08`：文档、切片、实体、检索结果、LLM 调用、原始/最终三元组及证据关联。
- `09` 至 `11`：该实验下已保存的评估记录、指标和实体对齐明细。

## 使用说明

- CSV 使用 UTF-8 with BOM 编码，可直接用 Excel 打开。
- `05_LLM调用记录.csv` 和 `01_文档.csv` 可能包含原始文本、Prompt 或模型响应，仅应在受控环境中使用。
- 空 CSV 表示该实验该阶段没有产生对应记录，并非导出失败。
"""


def build_experiment_package(export_data: Mapping[str, object]) -> tuple[bytes, dict[str, int]]:
    """Return a ZIP payload and row counts without writing temporary files."""
    run = dict(export_data.get("run") or {})
    archive = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("README_导出说明.md", _readme(run).encode("utf-8"))
        package.writestr(
            "00_运行信息.json",
            json.dumps(run, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        )
        for key, filename in EXPORT_LAYOUT:
            rows = list(export_data.get(key) or [])
            counts[key] = len(rows)
            package.writestr(filename, _csv_bytes(rows))
    return archive.getvalue(), counts
