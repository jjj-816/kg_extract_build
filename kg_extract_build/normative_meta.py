"""规范族与版本登记模型及校验（不依赖 I/O）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .normative import stable_hash


VERSION_STATUSES = frozenset(
    {"pending_confirmation", "effective", "superseded", "repealed", "unknown"}
)


@dataclass(frozen=True)
class FamilyDraft:
    canonical_name: str
    standard_code_base: str | None = None


@dataclass(frozen=True)
class VersionDraft:
    family_id: str
    document_id: int
    display_name: str
    standard_code: str | None = None
    version_year: int | None = None
    publication_year: int | None = None
    effective_year: int | None = None
    invalid_year: int | None = None
    status: str = "pending_confirmation"
    supersedes_version_id: str | None = None
    metadata_confirmed: bool = False
    metadata_hash: str = ""
    version_id: str = ""


def build_metadata_hash(draft: VersionDraft) -> str:
    return stable_hash(
        {
            "family_id": draft.family_id,
            "display_name": draft.display_name,
            "standard_code": draft.standard_code,
            "version_year": draft.version_year,
            "publication_year": draft.publication_year,
            "effective_year": draft.effective_year,
            "invalid_year": draft.invalid_year,
            "status": draft.status,
            "supersedes_version_id": draft.supersedes_version_id,
        }
    )


def validate_version_draft(draft: VersionDraft, existing: Iterable[VersionDraft]) -> None:
    if draft.status not in VERSION_STATUSES:
        raise ValueError(f"未知版本状态：{draft.status}")
    if (
        draft.invalid_year is not None
        and draft.effective_year is not None
        and draft.effective_year > draft.invalid_year
    ):
        raise ValueError("生效年份不能晚于失效年份")
    if draft.status in {"superseded", "repealed"} and draft.invalid_year is None:
        raise ValueError("superseded/repealed 版本必须确认 invalid_year")
    if draft.metadata_confirmed and not draft.metadata_hash:
        raise ValueError("已确认的版本必须提供 metadata_hash")
    # 新版本 id 尚未分配，环只能沿要挂接的 supersedes 链检测。
    if draft.supersedes_version_id and detect_supersede_cycle(draft.supersedes_version_id, list(existing)):
        raise ValueError("替代关系形成循环，拒绝保存")


def detect_supersede_cycle(version_id: str, existing: Iterable[VersionDraft]) -> bool:
    versions = {item.version_id: item for item in existing if item.version_id}
    visited: set[str] = set()
    current = version_id
    while current:
        if current in visited:
            return True
        visited.add(current)
        item = versions.get(current)
        if item is None or item.supersedes_version_id is None:
            return False
        current = item.supersedes_version_id
    return False
