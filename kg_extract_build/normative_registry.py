"""文档 → 规范版本 + 不可变条款集的登记工作流。"""

from __future__ import annotations

import re
import uuid

from .normative import PARSER_VERSION, parse_normative_clauses, stable_hash
from .normative_meta import FamilyDraft, VersionDraft, build_metadata_hash, validate_version_draft
from .normative_persistence import NormativeStore


_YEAR_RE = re.compile(r"(20\d{2})\s*年")


def guess_version_year(text: str) -> int | None:
    match = _YEAR_RE.search(str(text or ""))
    return int(match.group(1)) if match else None


def register_version(
    store: NormativeStore,
    *,
    document_id: int,
    file_name: str,
    content: str,
    display_name: str,
    effective_year: int | None,
    status: str,
    supersedes_version_id: str | None = None,
    invalid_year: int | None = None,
    standard_code: str | None = None,
) -> dict:
    # 1) 族：canonical_name 取文件名去扩展名；已存在则复用。
    canonical = re.sub(r"\.(md|txt)$", "", file_name)
    rows = store._read(
        "SELECT family_id FROM kg_normative_family WHERE canonical_name=%s LIMIT 1",
        (canonical,),
    )
    if rows:
        family_id = rows[0]["family_id"]
    else:
        family_id = str(uuid.uuid4())
        store.save_family(family_id, FamilyDraft(canonical_name=canonical))

    # 2) 版本：登记后按当前确认状态存 metadata_hash。
    draft = VersionDraft(
        family_id=family_id,
        document_id=document_id,
        display_name=display_name,
        standard_code=standard_code,
        version_year=effective_year,
        effective_year=effective_year,
        invalid_year=invalid_year,
        status=status,
        supersedes_version_id=supersedes_version_id,
        metadata_confirmed=status != "pending_confirmation",
    )
    draft = VersionDraft(**{**draft.__dict__, "metadata_hash": build_metadata_hash(draft)})
    validate_version_draft(draft, [])
    version_id = store.save_version(draft)

    # 3) 条款集：每次登记新生成，不覆盖历史。
    clauses = parse_normative_clauses(content)
    clause_set_id = str(uuid.uuid4())
    store.save_clause_set(
        clause_set_id, version_id, document_id,
        stable_hash({"content": content}), PARSER_VERSION,
        stable_hash({"parser": "parse_normative_clauses"}), "published",
    )
    if clauses:
        store.save_clauses(clause_set_id, version_id, document_id, clauses)

    return {
        "family_id": family_id,
        "version_id": version_id,
        "clause_set_id": clause_set_id,
        "clause_count": len(clauses),
    }
