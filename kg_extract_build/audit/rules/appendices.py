"""附录模板字段与固定区域检查。"""

import re

from .fields import is_meaningful


def appendix_corpus(evidence) -> str:
    raw = "\n".join(item.get("raw_text", "") + " " + " ".join(str(cell) for row in ((item.get("table_json") or {}).get("rows") or []) for cell in row) for item in evidence)
    # Word 单元格会把标签拆成纵向单字或换行；统一为无空白的连续文本。
    return re.sub(r"\s+", "", raw)


def missing_regions(corpus: str, regions: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(region for region in regions if region.replace(" ", "") not in corpus)


def has_invalid_work_content(corpus: str) -> bool:
    return "工作内容" in corpus and "详见方案" in corpus
