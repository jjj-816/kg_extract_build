"""只读、受限且可回溯的历史案例图检索端口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol


class GraphUnavailable(RuntimeError):
    pass


class ReadOnlyGraph(Protocol):
    def query_clues(self, *, task_id: str, query: str, relationship_types: tuple[str, ...], max_hops: int) -> Iterable[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class GraphClue:
    clue_id: str
    task_id: str
    relationship_type: str
    hops: int
    assertion_id: str
    source_document_id: str
    evidence_sentence: str
    summary: str


@dataclass(frozen=True)
class GraphRetrievalResult:
    clues: tuple[GraphClue, ...]
    degraded: bool = False
    diagnostic: str | None = None
    queries: tuple[str, ...] = ()
    relationship_types: tuple[str, ...] = ()
    raw_hit_count: int = 0


def retrieve_bounded_clues(graph: ReadOnlyGraph, *, task_id: str, query: str, relationship_whitelist: Iterable[str], max_hops: int = 2) -> GraphRetrievalResult:
    allowed = tuple(dict.fromkeys(str(item) for item in relationship_whitelist if str(item).strip()))
    if max_hops < 1 or max_hops > 2:
        raise ValueError("图检索路径上限必须为 1 或 2 跳")
    try:
        rows = list(graph.query_clues(task_id=task_id, query=query, relationship_types=allowed, max_hops=max_hops))
        clues = []
        for row in rows:
            relationship = str(row.get("relationship_type", ""))
            hops = int(row.get("hops", 0))
            if relationship not in allowed or hops < 1 or hops > max_hops:
                continue
            if not row.get("confirmed_case", False):
                continue
            required = ("clue_id", "assertion_id", "source_document_id", "evidence_sentence")
            if not all(row.get(key) for key in required):
                continue
            clues.append(GraphClue(str(row["clue_id"]), task_id, relationship, hops, str(row["assertion_id"]), str(row["source_document_id"]), str(row["evidence_sentence"]), str(row.get("summary", ""))))
        if not clues:
            return GraphRetrievalResult((), False, "未找到满足关系白名单和两跳限制的已确认历史案例线索", (), allowed, len(rows))
        return GraphRetrievalResult(tuple(clues), False, None, (), allowed, len(clues))
    except Exception as exc:
        return GraphRetrievalResult((), True, f"图服务不可用，已降级为信息不足：{exc}")
