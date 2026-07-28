# 施工方案智能审核方法插图实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 Python 和 Matplotlib 生成一张中文、Nature 风格、可编辑且可复现的施工方案智能审核方法总览图。

**Architecture:** 一个独立绘图脚本负责布局、图元、中文标签和三种格式导出；一个轻量测试文件验证语义标签、画布尺寸、SVG 可编辑文本和导出完整性。图形采用横向五阶段叙事，其中“双源分层检索”和“双证据门控”构成视觉中心。

**Tech Stack:** Python 3、Matplotlib、Pillow、pytest、SVG、PDF、PNG

## Global Constraints

- 仅使用 Python 和 Matplotlib完成绘制、预览、导出和视觉质检。
- 最终尺寸约为 180 mm × 115 mm。
- 主输出为文本保持可编辑的 SVG，辅助输出为 PDF 和 600 dpi PNG。
- 使用白色背景、低饱和配色和从左向右的阅读方向。
- 历史案例知识图谱只提供查询扩展和工程合理性线索，不得表现为规范证据。
- 大语言模型只生成智能审核初稿，最终结论必须由人工复核。
- 不展示未由实验数据支持的性能数值。

---

### Task 1: 建立可测试的图形语义契约

**Files:**
- Create: `figures/test_construction_scheme_audit_method.py`
- Create: `figures/construction_scheme_audit_method.py`

**Interfaces:**
- Consumes: 已确认的中文设计说明。
- Produces: `FIGURE_SIZE_INCHES: tuple[float, float]`、`REQUIRED_LABELS: tuple[str, ...]`、`build_figure() -> matplotlib.figure.Figure`。

- [ ] **Step 1: 编写失败测试**

```python
from construction_scheme_audit_method import (
    FIGURE_SIZE_INCHES,
    REQUIRED_LABELS,
    build_figure,
)


def test_figure_contract():
    fig = build_figure()
    labels = {text.get_text() for text in fig.findobj(match=lambda x: hasattr(x, "get_text"))}

    assert FIGURE_SIZE_INCHES == (7.0866, 4.5276)
    assert set(REQUIRED_LABELS).issubset(labels)
    assert len(fig.axes) == 1
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest figures/test_construction_scheme_audit_method.py::test_figure_contract -v`

Expected: FAIL，原因是 `construction_scheme_audit_method` 模块尚不存在。

- [ ] **Step 3: 实现最小语义骨架**

在 `figures/construction_scheme_audit_method.py` 中定义：

```python
FIGURE_SIZE_INCHES = (7.0866, 4.5276)
REQUIRED_LABELS = (
    "施工方案",
    "结构化证据块",
    "审核任务路由",
    "规范条款向量库",
    "历史案例知识图谱",
    "双证据门控",
    "智能审核初稿",
    "人工复核",
)


def build_figure():
    fig, ax = plt.subplots(figsize=FIGURE_SIZE_INCHES)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    for index, label in enumerate(REQUIRED_LABELS):
        ax.text(0.05, 0.95 - index * 0.1, label)
    return fig
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `python -m pytest figures/test_construction_scheme_audit_method.py::test_figure_contract -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add figures/test_construction_scheme_audit_method.py figures/construction_scheme_audit_method.py
git commit -m "test: define audit method figure contract"
```

### Task 2: 绘制完整的横向方法总览图

**Files:**
- Modify: `figures/construction_scheme_audit_method.py`
- Modify: `figures/test_construction_scheme_audit_method.py`

**Interfaces:**
- Consumes: `build_figure()` 的单轴画布和 `REQUIRED_LABELS`。
- Produces: `add_round_box(...)`、`add_arrow(...)`、`add_badge(...)`、`add_document_icon(...)`、`add_database_icon(...)`、`add_graph_icon(...)`，以及完整方法图。

- [ ] **Step 1: 扩展失败测试**

```python
def test_visual_structure_contains_distinct_evidence_roles():
    fig = build_figure()
    all_text = "\n".join(
        text.get_text()
        for text in fig.findobj(match=lambda x: hasattr(x, "get_text"))
    )

    assert "权威合规证据" in all_text
    assert "工程合理性线索" in all_text
    assert "不得作为法规依据" in all_text
    assert "最终结论" in all_text
    assert len(fig.axes[0].patches) >= 20
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest figures/test_construction_scheme_audit_method.py::test_visual_structure_contains_distinct_evidence_roles -v`

Expected: FAIL，原因是完整图形结构和角色标签尚未实现。

- [ ] **Step 3: 实现完整绘图**

使用 Matplotlib patch 和 line primitives 完成下列结构：

```text
施工方案
  → 结构化解析与人工上下文确认
  → 确定性检查 / JSA 规则 / 语义审核
  → 规范条款向量库 ──权威合规证据──┐
     历史案例知识图谱 ──查询扩展────┼→ 双证据门控 + 受约束 LLM
                          └─合理性线索┘
  → 结论校验与证据回填
  → 智能审核初稿
  → 人工复核
  → 最终审核报告
```

配色固定为：

```python
COLORS = {
    "blue": "#2F6B9A",
    "blue_light": "#DCEAF4",
    "teal": "#3D8B7D",
    "teal_light": "#DDEFEA",
    "violet": "#7566A8",
    "violet_light": "#E9E4F3",
    "orange": "#C96C3B",
    "orange_light": "#F6E4D8",
    "grey": "#59636E",
    "grey_light": "#EDF0F2",
    "ink": "#263238",
}
```

设置 `svg.fonttype = "none"`、`pdf.fonttype = 42`，优先使用系统可用的
`Microsoft YaHei`、`SimHei` 或 `Noto Sans CJK SC`。用统一圆角、线宽和
箭头样式组织视觉层级。

- [ ] **Step 4: 运行结构测试**

Run: `python -m pytest figures/test_construction_scheme_audit_method.py -v`

Expected: 两个测试均 PASS。

- [ ] **Step 5: 提交**

```bash
git add figures/construction_scheme_audit_method.py figures/test_construction_scheme_audit_method.py
git commit -m "feat: draw evidence-constrained audit method figure"
```

### Task 3: 导出并验证论文成品

**Files:**
- Modify: `figures/construction_scheme_audit_method.py`
- Modify: `figures/test_construction_scheme_audit_method.py`
- Create: `figures/output/construction_scheme_audit_method.svg`
- Create: `figures/output/construction_scheme_audit_method.pdf`
- Create: `figures/output/construction_scheme_audit_method.png`

**Interfaces:**
- Consumes: `build_figure() -> Figure`。
- Produces: `export_figure(output_dir: Path) -> dict[str, Path]` 和三种论文插图文件。

- [ ] **Step 1: 编写失败的导出测试**

```python
from xml.etree import ElementTree

from construction_scheme_audit_method import export_figure


def test_exports_are_complete_and_editable(tmp_path):
    outputs = export_figure(tmp_path)

    assert set(outputs) == {"svg", "pdf", "png"}
    assert all(path.exists() and path.stat().st_size > 10_000 for path in outputs.values())

    svg_root = ElementTree.parse(outputs["svg"]).getroot()
    text_nodes = svg_root.findall(".//{http://www.w3.org/2000/svg}text")
    assert len(text_nodes) >= 20

    image = Image.open(outputs["png"])
    assert image.width >= 4000
    assert image.height >= 2500
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest figures/test_construction_scheme_audit_method.py::test_exports_are_complete_and_editable -v`

Expected: FAIL，原因是 `export_figure` 尚未实现。

- [ ] **Step 3: 实现导出函数**

```python
def export_figure(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig = build_figure()
    base = output_dir / "construction_scheme_audit_method"
    outputs = {
        "svg": base.with_suffix(".svg"),
        "pdf": base.with_suffix(".pdf"),
        "png": base.with_suffix(".png"),
    }
    fig.savefig(outputs["svg"], bbox_inches="tight", facecolor="white")
    fig.savefig(outputs["pdf"], bbox_inches="tight", facecolor="white")
    fig.savefig(outputs["png"], dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return outputs
```

- [ ] **Step 4: 生成成品并运行自动质检**

Run: `python figures/construction_scheme_audit_method.py`

Expected: 在 `figures/output/` 中生成 SVG、PDF 和 PNG。

Run: `python -m pytest figures/test_construction_scheme_audit_method.py -v`

Expected: 三个测试均 PASS，且无缺字、字体回退或裁切警告。

- [ ] **Step 5: 执行视觉质检**

检查 600 dpi PNG，确认：

- 所有中文标签清晰且未裁切；
- 规范证据和图谱线索使用不同颜色及明确文字说明；
- 双证据门控是最显著的视觉焦点；
- 箭头不存在错误交叉或方向歧义；
- 人工复核位于模型输出之后；
- 最终论文宽度下文字仍可辨认。

如发现问题，只修改 `figures/construction_scheme_audit_method.py`，重新运行
全部测试并重新导出三种格式。

- [ ] **Step 6: 提交**

```bash
git add figures/construction_scheme_audit_method.py \
  figures/test_construction_scheme_audit_method.py \
  figures/output/construction_scheme_audit_method.svg \
  figures/output/construction_scheme_audit_method.pdf \
  figures/output/construction_scheme_audit_method.png
git commit -m "feat: export publication-ready audit method figure"
```
