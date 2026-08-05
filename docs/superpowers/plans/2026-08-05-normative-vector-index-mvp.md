# 规范条款向量索引 MVP 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐"规范条款向量索引"半场，打通 规范登记→条款落库→分段→MiniLM 编码→Milvus 集合族→发布版→纯向量检索预览 的 MVP 闭环。

**Architecture:** 新增 8 个独立模块（`normative_meta/persistence/segmentation/encoder/vector_store/indexer/search/dashboard_normative`），复用 `normative.py` 已有纯函数（`parse_normative_clauses`、`build_index_fingerprint`、`applicable_versions`、`stable_hash`）。MySQL 为版本/年份/索引状态唯一真实来源，Milvus 只存稳定标识+向量。沿用 `MySQLExperimentStore._write/_read` 连接与事务模式、`CorpusRetriever` 的懒加载模型模式、测试用 fake 模块注入模式。

**Tech Stack:** Python 3.11（env_agent）、pymilvus 2.6.16、sentence-transformers 5.1.2、numpy、streamlit、pymysql。

## Global Constraints

- 运行环境 python：`D:/ProgramData/anaconda3/envs/env_agent/python.exe`（所有 pytest / python 命令用此解释器）。
- Milvus 服务由用户在 Docker 自行启动，URI 默认 `http://127.0.0.1:19530`；MVP 代码只接真实服务（不用 Milvus Lite）。
- 集合族前缀默认 `kg_normative_clauses`；MVP 只实现 MiniLM `paraphrase-multilingual-MiniLM-L12-v2`（384 维）。
- 复用 `normative.py` 现有函数，不复制实现：`stable_hash`、`normalize_clause_text`、`parse_normative_clauses`、`ClauseDraft`、`NormativeVersionCandidate`、`applicable_versions`、`build_index_fingerprint`。
- 8 张 `kg_normative_*` 表已存在（`kg_extract_build/schema.sql`），本计划只写数据、不改 schema。
- 严禁在 `kg_triplet` 增加 `source_type` 列；来源一律经 `kg_document.source_type` 联表。
- Milvus 记录只含稳定标识 + 向量；候选版本以 MySQL 计算为准。
- 单元测试不依赖真实 MySQL / Milvus / 模型，用注入 fake；端到端冒烟（Task 13）才要求 Milvus 与 MiniLM 模型就位。
- 依赖 `pytest`；已有 57+ 测试回归不得破坏（`python -m pytest kg_extract_build/tests -q` 需保持通过）。

---

### Task 1: 规范索引配置项

**Files:**
- Modify: `kg_extract_build/settings.py`（追加 NORM_* 常量）
- Modify: `kg_extract_build/.env.example`
- Test: `kg_extract_build/tests/test_settings_normative.py`

**Interfaces:**
- Produces: `settings.NORM_VECTOR_MODEL_PATH`（Path）、`settings.NORM_MILVUS_URI`（str）、`settings.NORM_MILVUS_COLLECTION_PREFIX`（str）、`settings.NORM_MILVUS_TOKEN`（str）、`settings.NORM_MILVUS_ENABLED`（bool）。后续所有模块从 `settings` 读取。

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_settings_normative.py`：
```python
import os
import tempfile
import unittest
from pathlib import Path

from kg_extract_build import settings


class NormativeSettingsTests(unittest.TestCase):
    def test_norm_model_path_default(self):
        self.assertEqual(
            settings.NORM_VECTOR_MODEL_PATH,
            Path(settings.BASE_DIR)
            / "models" / "paraphrase-multilingual-MiniLM-L12-v2",
        )

    def test_norm_milvus_defaults(self):
        self.assertEqual(settings.NORM_MILVUS_URI, "http://127.0.0.1:19530")
        self.assertEqual(settings.NORM_MILVUS_COLLECTION_PREFIX, "kg_normative_clauses")
        self.assertFalse(settings.NORM_MILVUS_ENABLED)

    def test_env_override(self):
        with tempfile.TemporaryDirectory() as folder:
            os.environ["KG_NORM_MILVUS_COLLECTION_PREFIX"] = "kg_norm_custom"
            try:
                import importlib
                importlib.reload(settings)
                self.assertEqual(settings.NORM_MILVUS_COLLECTION_PREFIX, "kg_norm_custom")
            finally:
                os.environ.pop("KG_NORM_MILVUS_COLLECTION_PREFIX", None)
                importlib.reload(settings)
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_settings_normative.py -v`
Expected: FAIL（`AttributeError: module 'kg_extract_build.settings' has no attribute 'NORM_VECTOR_MODEL_PATH'`）

- [ ] **Step 3: 实现**

在 `kg_extract_build/settings.py` 末尾追加：
```python
NORM_VECTOR_MODEL_PATH = env_path(
    "KG_NORM_VECTOR_MODEL_PATH",
    BASE_DIR / "models" / "paraphrase-multilingual-MiniLM-L12-v2",
)
NORM_MILVUS_URI = os.getenv("KG_NORM_MILVUS_URI", "http://127.0.0.1:19530")
NORM_MILVUS_TOKEN = os.getenv("KG_NORM_MILVUS_TOKEN", "")
NORM_MILVUS_COLLECTION_PREFIX = os.getenv(
    "KG_NORM_MILVUS_COLLECTION_PREFIX", "kg_normative_clauses"
)
NORM_MILVUS_ENABLED = env_bool("KG_NORM_MILVUS_ENABLED", False)
```

在 `kg_extract_build/.env.example` 追加：
```
# 规范条款向量索引（MVP：MiniLM 单模型，接真实 Milvus 服务）
KG_NORM_VECTOR_MODEL_PATH=
KG_NORM_MILVUS_ENABLED=0
KG_NORM_MILVUS_URI=http://127.0.0.1:19530
KG_NORM_MILVUS_TOKEN=
KG_NORM_MILVUS_COLLECTION_PREFIX=kg_normative_clauses
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_settings_normative.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/settings.py kg_extract_build/.env.example kg_extract_build/tests/test_settings_normative.py
git commit -m "feat: 规范索引 NORM_* 配置项"
```

---

### Task 2: 规范元数据模型与登记校验

**Files:**
- Create: `kg_extract_build/normative_meta.py`
- Test: `kg_extract_build/tests/test_normative_meta.py`

**Interfaces:**
- Consumes: `normative.stable_hash`。
- Produces:
  - `VERSION_STATUSES: frozenset[str]`
  - `@dataclass(frozen=True) FamilyDraft(canonical_name: str, standard_code_base: str | None = None)`
  - `@dataclass(frozen=True) VersionDraft(family_id: str, document_id: int, display_name: str, standard_code: str | None = None, version_year: int | None = None, publication_year: int | None = None, effective_year: int | None = None, invalid_year: int | None = None, status: str = "pending_confirmation", supersedes_version_id: str | None = None, metadata_confirmed: bool = False, metadata_hash: str = "", version_id: str = "")`
  - `build_metadata_hash(draft: VersionDraft) -> str`
  - `validate_version_draft(draft: VersionDraft, existing: list[VersionDraft]) -> None`（违规抛 `ValueError`；环检测沿 `supersedes_version_id` 链）
  - `detect_supersede_cycle(version_id: str, existing: list[VersionDraft]) -> bool`

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_normative_meta.py`：
```python
import unittest

from kg_extract_build.normative_meta import (
    VERSION_STATUSES,
    VersionDraft,
    build_metadata_hash,
    detect_supersede_cycle,
    validate_version_draft,
)


def draft(**overrides):
    base = dict(
        family_id="family-1",
        document_id=36,
        display_name="Q/SY 2000-2020 有限空间作业",
        standard_code="Q/SY 2000-2020",
        version_year=2020,
        effective_year=2020,
        invalid_year=None,
        status="effective",
        supersedes_version_id=None,
        metadata_confirmed=True,
    )
    base.update(overrides)
    return VersionDraft(**base)


class NormativeMetaTests(unittest.TestCase):
    def test_statuses_contain_design_values(self):
        self.assertEqual(
            VERSION_STATUSES,
            {"pending_confirmation", "effective", "superseded", "repealed", "unknown"},
        )

    def test_effective_after_invalid_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "生效年份不能晚于失效年份"):
            validate_version_draft(draft(effective_year=2021, invalid_year=2020), [])

    def test_superseded_without_invalid_year_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "必须确认 invalid_year"):
            validate_version_draft(draft(status="superseded", invalid_year=None), [])

    def test_valid_draft_passes(self):
        validate_version_draft(draft(), [])

    def test_supersede_cycle_is_detected(self):
        a = draft(version_id="v1", supersedes_version_id="v2")
        b = draft(version_id="v2", family_id="family-1", document_id=37, display_name="新版",
                  standard_code="Q/SY 2000-2025", version_year=2025, effective_year=2025,
                  supersedes_version_id="v1")
        self.assertTrue(detect_supersede_cycle("v1", [a, b]))
        with self.assertRaisesRegex(ValueError, "循环"):
            validate_version_draft(draft(supersedes_version_id="v1"), [a, b])

    def test_metadata_hash_is_stable_and_sensitive(self):
        base = draft()
        self.assertEqual(build_metadata_hash(base), build_metadata_hash(base))
        changed = draft(display_name="其他名称")
        self.assertNotEqual(build_metadata_hash(base), build_metadata_hash(changed))
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_meta.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'kg_extract_build.normative_meta'`）

- [ ] **Step 3: 实现**

`kg_extract_build/normative_meta.py`：
```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_meta.py -v`
Expected: PASS（若 `test_supersede_cycle_is_detected` 构造不触发，按循环遍历修正测试中 a/b 的 `supersedes_version_id` 指向，使 `v1 -> v2 -> v1` 成环）

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/normative_meta.py kg_extract_build/tests/test_normative_meta.py
git commit -m "feat: 规范版本登记模型与校验"
```

---

### Task 3: 规范持久化层（登记 + 条款落库）

**Files:**
- Create: `kg_extract_build/normative_persistence.py`
- Test: `kg_extract_build/tests/test_normative_persistence.py`

**Interfaces:**
- Consumes: `MySQLExperimentStore`（提供 `_write/_read`）、`normative_meta.VersionDraft`、`normative.ClauseDraft`。
- Produces:
  - `class NormativeStore`：构造 `NormativeStore(backend)`，`backend` 需有 `_write(sql, params=None) -> int` 与 `_read(sql, params=None) -> list[dict]`（`MySQLExperimentStore` 直接满足）。
  - `save_family(family_id: str, family: FamilyDraft) -> None`
  - `save_version(draft: VersionDraft) -> str`（返回新 `version_id`）
  - `get_version(version_id: str) -> dict | None`
  - `list_versions(family_id: str | None = None) -> list[dict]`
  - `version_candidates() -> list[NormativeVersionCandidate]`
  - `save_clause_set(clause_set_id, version_id, document_id, source_content_hash, parser_version, parser_config_hash, status) -> None`
  - `save_clauses(clause_set_id, version_id, document_id, clauses: list[ClauseDraft]) -> None`
  - `get_clauses(clause_set_id) -> list[dict]`
  - `has_normative_references(document_id: int) -> bool`

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_normative_persistence.py`（用内存 backend 记录 SQL 与读回数据）：
```python
import re
import unittest
from collections import defaultdict

from kg_extract_build.normative import ClauseDraft, NormativeVersionCandidate
from kg_extract_build.normative_meta import VersionDraft
from kg_extract_build.normative_persistence import NormativeStore


class InMemoryBackend:
    """记录 INSERT/UPDATE 到内存表，按 SELECT 表名回放缓存行。"""

    def __init__(self):
        self.rows: dict[str, list[dict]] = defaultdict(list)
        self.statements: list[str] = []
        self._auto = 1

    def _write(self, sql, params=None, many=False):
        self.statements.append(sql)
        table = re.search(r"(?:INSERT INTO|UPDATE)\s+(\w+)", sql).group(1)
        if not sql.strip().upper().startswith("INSERT"):
            return 1
        rows = [tuple(params or ())] if not many else [tuple(p) for p in (params or [])]
        cols = [c.strip().strip("`") for c in re.search(r"\(([^)]+)\)", sql).group(1).split(",")]
        last = None
        for values in rows:
            row = dict(zip(cols, values))
            pk = [c for c in cols if c in {"version_id", "clause_set_id", "index_id"}]
            key = row.get(pk[0], self._auto) if pk else self._auto
            if not pk:
                row["id"] = self._auto
                self._auto += 1
            existing = [r for r in self.rows[table] if r.get(pk[0]) == key] if pk else []
            if existing:
                existing[0].update(row)
            else:
                self.rows[table].append(row)
            last = key
        return last

    def _read(self, sql, params=None):
        table = re.search(r"FROM\s+(\w+)", sql).group(1)
        return [dict(r) for r in self.rows[table]]


class NormativePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.backend = InMemoryBackend()
        self.store = NormativeStore(self.backend)

    def test_save_family_and_version_roundtrip(self):
        self.store.save_family("family-1", "有限空间作业安全规程", "Q/SY 2000")
        version_id = self.store.save_version(
            VersionDraft(
                family_id="family-1", document_id=36, display_name="Q/SY 2000-2020",
                effective_year=2020, status="effective", metadata_confirmed=True,
            )
        )
        row = self.store.get_version(version_id)
        self.assertEqual(row["family_id"], "family-1")
        self.assertEqual(row["effective_year"], 2020)

    def test_save_clause_set_and_clauses(self):
        self.store.save_clause_set("set-1", "version-1", 36, "hash-src", "normative-clause-v1", "cfg", "published")
        self.store.save_clauses(
            "set-1", "version-1", 36,
            [ClauseDraft("第二十条", ("总则",), None, "作业前应通风。", "作业前应通风。", 0, 8, "structured")],
        )
        rows = self.store.get_clauses("set-1")
        self.assertEqual(rows[0]["clause_number"], "第二十条")
        self.assertEqual(rows[0]["raw_text"], "作业前应通风。")

    def test_has_normative_references_true_when_version_exists(self):
        self.store.save_family("family-1", "有限空间作业安全规程", "Q/SY 2000")
        self.store.save_version(
            VersionDraft(family_id="family-1", document_id=36, display_name="v",
                         effective_year=2020, status="effective")
        )
        self.assertTrue(self.store.has_normative_references(36))

    def test_version_candidates_include_only_metadata_confirmed(self):
        self.store.save_family("family-1", "有限空间作业安全规程", "Q/SY 2000")
        self.store.save_version(
            VersionDraft(family_id="family-1", document_id=36, display_name="v",
                         effective_year=2020, status="effective", metadata_confirmed=True)
        )
        self.store.save_version(
            VersionDraft(family_id="family-1", document_id=37, display_name="u",
                         effective_year=2020, status="pending_confirmation", metadata_confirmed=False)
        )
        candidates = self.store.version_candidates()
        self.assertEqual([c.metadata_confirmed for c in candidates], [True])
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_persistence.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`kg_extract_build/normative_persistence.py`：
```python
"""规范族/版本/条款集/条款的 MySQL 持久化（只写已有 schema 表）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .normative import ClauseDraft, NormativeVersionCandidate, stable_hash
from .normative_meta import FamilyDraft, VersionDraft


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


class NormativeStore:
    """薄封装：把所有 SQL 委托给 backend（MySQLExperimentStore 满足接口）。"""

    def __init__(self, backend):
        self._backend = backend

    def _read(self, sql, params=None):
        return self._backend._read(sql, params)

    def _write(self, sql, params=None, many=False):
        return self._backend._write(sql, params, many=many)

    # ---- 族与版本 ----
    def save_family(self, family_id: str, family: FamilyDraft) -> None:
        self._backend._write(
            "INSERT INTO kg_normative_family "
            "(family_id, canonical_name, standard_code_base, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (family_id, family.canonical_name, family.standard_code_base, _utc_now(), _utc_now()),
        )

    def save_version(self, draft: VersionDraft) -> str:
        version_id = draft.version_id or str(uuid.uuid4())
        self._backend._write(
            "INSERT INTO kg_normative_version "
            "(version_id, family_id, document_id, display_name, standard_code, "
            " version_year, publication_year, effective_year, invalid_year, status, "
            " supersedes_version_id, metadata_confirmed, metadata_hash, confirmed_at, "
            " created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                version_id, draft.family_id, draft.document_id, draft.display_name,
                draft.standard_code, draft.version_year, draft.publication_year,
                draft.effective_year, draft.invalid_year, draft.status,
                draft.supersedes_version_id, int(draft.metadata_confirmed),
                draft.metadata_hash,
                _utc_now() if draft.metadata_confirmed else None,
                _utc_now(), _utc_now(),
            ),
        )
        return version_id

    def get_version(self, version_id: str) -> dict | None:
        rows = self._backend._read(
            "SELECT * FROM kg_normative_version WHERE version_id=%s", (version_id,)
        )
        return rows[0] if rows else None

    def list_versions(self, family_id: str | None = None) -> list[dict]:
        if family_id is None:
            return self._backend._read("SELECT * FROM kg_normative_version")
        return self._backend._read(
            "SELECT * FROM kg_normative_version WHERE family_id=%s", (family_id,)
        )

    def version_candidates(self) -> list[NormativeVersionCandidate]:
        rows = self._backend._read("SELECT * FROM kg_normative_version")
        return [
            NormativeVersionCandidate(
                version_id=r["version_id"],
                family_id=r["family_id"],
                effective_year=r["effective_year"],
                invalid_year=r["invalid_year"],
                metadata_confirmed=bool(r["metadata_confirmed"]),
                status=r["status"],
            )
            for r in rows
        ]

    # ---- 条款集与条款 ----
    def save_clause_set(
        self, clause_set_id, version_id, document_id, source_content_hash,
        parser_version, parser_config_hash, status,
    ) -> None:
        self._backend._write(
            "INSERT INTO kg_normative_clause_set "
            "(clause_set_id, version_id, document_id, source_content_hash, "
            " parser_version, parser_config_hash, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (clause_set_id, version_id, document_id, source_content_hash,
             parser_version, parser_config_hash, status, _utc_now()),
        )

    def save_clauses(self, clause_set_id, version_id, document_id, clauses) -> None:
        params = []
        for clause in clauses:
            params.append(
                (clause_set_id, version_id, document_id, clause.clause_number,
                 _json(clause.hierarchy_path), clause.clause_title,
                 clause.raw_text, clause.normalized_text,
                 clause.start_offset, clause.end_offset, clause.content_hash,
                 clause.parse_status, _utc_now())
            )
        self._backend._write(
            "INSERT INTO kg_normative_clause "
            "(clause_set_id, version_id, document_id, clause_number, hierarchy_path, "
            " clause_title, raw_text, normalized_text, start_offset, end_offset, "
            " content_hash, parse_status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            params,
            many=True,
        )

    def get_clauses(self, clause_set_id) -> list[dict]:
        return self._backend._read(
            "SELECT * FROM kg_normative_clause WHERE clause_set_id=%s", (clause_set_id,)
        )

    # ---- 生命周期 ----
    def has_normative_references(self, document_id: int) -> bool:
        for table in ("kg_normative_version", "kg_normative_clause_set", "kg_normative_clause"):
            rows = self._backend._read(
                f"SELECT 1 FROM {table} WHERE document_id=%s LIMIT 1", (document_id,)
            )
            if rows:
                return True
        return False


def _json(value):
    import json
    return json.dumps(list(value or ()), ensure_ascii=False)
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_persistence.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/normative_persistence.py kg_extract_build/tests/test_normative_persistence.py
git commit -m "feat: 规范登记与条款落库持久化"
```

---

### Task 4: 规范登记工作流（文档 → 版本 + 条款集）

**Files:**
- Create: `kg_extract_build/normative_registry.py`
- Test: `kg_extract_build/tests/test_normative_registry.py`

**Interfaces:**
- Consumes: `NormativeStore`、`parse_normative_clauses`、`build_metadata_hash`、`validate_version_draft`、`PARSER_VERSION`、`stable_hash`。
- Produces:
  - `guess_version_year(text: str) -> int | None`（正则 `(20\\d{2})\\s*年` 首个年份）
  - `register_version(store: NormativeStore, *, document_id: int, file_name: str, content: str, display_name: str, effective_year: int | None, status: str, supersedes_version_id: str | None = None, invalid_year: int | None = None, existing_versions: list[VersionDraft] | None = None) -> dict`：返回 `{"family_id", "version_id", "clause_set_id", "clause_count"}`。同一 `canonical_name` 复用族；重复登记同一文档时生成新 `clause_set_id` 且不删除旧条款。

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_normative_registry.py`：
```python
import unittest

from kg_extract_build.normative_persistence import NormativeStore
from kg_extract_build.normative_registry import (
    guess_version_year,
    register_version,
)

from test_normative_persistence import InMemoryBackend


class NormativeRegistryTests(unittest.TestCase):
    def setUp(self):
        self.store = NormativeStore(InMemoryBackend())

    def test_guess_year_from_text(self):
        self.assertEqual(guess_version_year("2020年发布"), 2020)
        self.assertIsNone(guess_version_year("无年份"))

    def test_register_creates_family_version_clauses(self):
        content = "# 总则\n\n第二十条 作业前应通风。\n\n5.1.2 应记录检测结果。\n"
        result = register_version(
            self.store, document_id=36, file_name="有限空间作业规程.md",
            content=content, display_name="有限空间作业规程 2020",
            effective_year=2020, status="effective",
        )
        self.assertEqual(result["clause_count"], 2)
        self.assertTrue(result["family_id"])
        self.assertTrue(result["version_id"])
        self.assertTrue(result["clause_set_id"])

    def test_reparse_creates_new_clause_set_not_overwrite(self):
        content = "# 总则\n\n第二十条 作业前应通风。\n"
        first = register_version(
            self.store, document_id=36, file_name="规程.md", content=content,
            display_name="规程 2020", effective_year=2020, status="effective",
        )
        content2 = "# 总则\n\n第二十条 作业前应通风。\n\n第二十一条 严禁违章。\n"
        second = register_version(
            self.store, document_id=36, file_name="规程.md", content=content2,
            display_name="规程 2020", effective_year=2020, status="effective",
        )
        self.assertNotEqual(first["clause_set_id"], second["clause_set_id"])
        # 新条款集含两条，旧条款集仍可读（不被覆盖）
        old_clauses = self.store.get_clauses(first["clause_set_id"])
        new_clauses = self.store.get_clauses(second["clause_set_id"])
        self.assertEqual(len(old_clauses), 1)
        self.assertEqual(len(new_clauses), 2)
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_registry.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`kg_extract_build/normative_registry.py`：
```python
"""文档 → 规范版本 + 不可变条款集的登记工作流。"""

from __future__ import annotations

import re
import uuid

from .normative import PARSER_VERSION, parse_normative_clauses, stable_hash
from .normative_meta import FamilyDraft, VersionDraft, build_metadata_hash
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
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_registry.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/normative_registry.py kg_extract_build/tests/test_normative_registry.py
git commit -m "feat: 规范登记工作流（族/版本/条款集一次登记）"
```

---

### Task 5: 长条款分段

**Files:**
- Create: `kg_extract_build/normative_segmentation.py`
- Test: `kg_extract_build/tests/test_normative_segmentation.py`

**Interfaces:**
- Consumes: `normative.ClauseDraft`、`stable_hash`。
- Produces:
  - `build_prefix(family_name: str, hierarchy_path: tuple[str, ...], clause_number: str | None) -> str`
  - `@dataclass(frozen=True) SegmentDraft(segment_index: int, embedding_text: str, token_count: int, text_hash: str)`
  - `segment_clause(clause: ClauseDraft, *, family_name: str, tokenizer, max_tokens: int = 128, overlap_tokens: int = 8) -> list[SegmentDraft]`
  - `tokenizer` 约定：`tokenizer(text) -> list`（返回 token 列表，`len()` 为 token 数）。

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_normative_segmentation.py`：
```python
import unittest

from kg_extract_build.normative import ClauseDraft
from kg_extract_build.normative_segmentation import (
    build_prefix,
    segment_clause,
)


def word_tokenizer(text):
    return text.split(" ")


class SegmentationTests(unittest.TestCase):
    def test_build_prefix_joins_identity(self):
        self.assertEqual(
            build_prefix("规程", ("第二章", "2.1"), "第二十条"),
            "【规范：规程 第二章/2.1 第二十条】",
        )

    def test_short_clause_is_single_segment(self):
        clause = ClauseDraft("第二十条", ("总则",), None,
                             "作业前应通风。", "作业前应通风。", 0, 8, "structured")
        segments = segment_clause(
            clause, family_name="规程", tokenizer=word_tokenizer, max_tokens=128,
        )
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].segment_index, 0)
        self.assertIn("作业前应通风", segments[0].embedding_text)

    def test_long_clause_splits_with_prefix_and_overlap(self):
        body = " ".join(["词"] * 100)
        clause = ClauseDraft("第二十条", ("总则",), None,
                             body, body, 0, len(body), "structured")
        segments = segment_clause(
            clause, family_name="规程", tokenizer=word_tokenizer,
            max_tokens=50, overlap_tokens=5,
        )
        self.assertGreater(len(segments), 1)
        for seg in segments:
            self.assertIn("第二十条", seg.embedding_text)
            self.assertLessEqual(seg.token_count, 50)

    def test_no_segment_silently_drops_body(self):
        body = " ".join(["词"] * 100)
        clause = ClauseDraft(None, ("附录",), None, body, body, 0, len(body), "fallback")
        segments = segment_clause(
            clause, family_name="规程", tokenizer=word_tokenizer, max_tokens=30, overlap_tokens=4,
        )
        joined = " ".join(s.embedding_text for s in segments)
        self.assertGreaterEqual(len(joined.replace("【规范：规程 附录】", "").split(" ")), 100)
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_segmentation.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`kg_extract_build/normative_segmentation.py`：
```python
"""逻辑条款 → 物理向量片段（按 token 上限分段，加身份前缀，不静默截断）。"""

from __future__ import annotations

from dataclasses import dataclass

from .normative import ClauseDraft, stable_hash


def build_prefix(family_name: str, hierarchy_path: tuple[str, ...], clause_number: str | None) -> str:
    path = "/".join(str(item) for item in hierarchy_path) if hierarchy_path else "正文"
    number = clause_number or ""
    return f"【规范：{family_name} {path}{(' ' + number) if number else ''}】"


@dataclass(frozen=True)
class SegmentDraft:
    segment_index: int
    embedding_text: str
    token_count: int
    text_hash: str


def _count(tokenizer, text: str) -> int:
    return len(tokenizer(text))


def segment_clause(
    clause: ClauseDraft, *,
    family_name: str,
    tokenizer,
    max_tokens: int = 128,
    overlap_tokens: int = 8,
) -> list[SegmentDraft]:
    prefix = build_prefix(family_name, clause.hierarchy_path, clause.clause_number)
    body = clause.raw_text
    full = f"{prefix}\n{body}"
    if _count(tokenizer, full) <= max_tokens:
        return [SegmentDraft(0, full, _count(tokenizer, full), stable_hash({"t": full}))]

    words = body.split()
    segments: list[SegmentDraft] = []
    index = 0
    start = 0
    while start < len(words):
        chunk: list[str] = []
        budget = max_tokens - _count(tokenizer, prefix)
        for word in words[start:]:
            cost = _count(tokenizer, word) + 1
            if chunk and budget - cost < 0:
                break
            chunk.append(word)
            budget -= cost
        if not chunk:
            chunk = words[start:start + 1]
        advance = max(1, len(chunk) - overlap_tokens)
        text = f"{prefix}\n{' '.join(chunk)}"
        segments.append(
            SegmentDraft(index, text, _count(tokenizer, text), stable_hash({"t": text}))
        )
        start += advance
        index += 1
    return segments
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_segmentation.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/normative_segmentation.py kg_extract_build/tests/test_normative_segmentation.py
git commit -m "feat: 长条款 token 分段（前缀+重叠+不截断）"
```

---

### Task 6: MiniLM 编码器与 encoder_profile

**Files:**
- Create: `kg_extract_build/normative_encoder.py`
- Test: `kg_extract_build/tests/test_normative_encoder.py`

**Interfaces:**
- Consumes: `normative.stable_hash`。
- Produces:
  - `@dataclass(frozen=True) EncoderProfile(embedding_model_key: str, embedding_model_revision: str, embedding_dimension: int, query_prefix: str = "", document_prefix: str = "", pooling: str = "mean", normalize: bool = True, max_input_tokens: int = 128)`
  - `build_encoder_profile_hash(profile: EncoderProfile) -> str`
  - `miniLM_PROFILE = EncoderProfile(embedding_model_key="paraphrase-multilingual-MiniLM-L12-v2", embedding_model_revision=..., embedding_dimension=384, ...)`（revision 运行时用 `model_revision` 填充）
  - `model_revision(model_path) -> str`（对模型目录下 config.json 等文件做稳定哈希，目录不存在时退化为路径字符串哈希）
  - `class NormativeEncoder`：`__init__(model_path, profile)` 懒加载 `SentenceTransformer`；`encode_documents(texts) -> np.ndarray`（加 `document_prefix` 并归一化）；`encode_query(text) -> np.ndarray`（加 `query_prefix` 并归一化）；`tokenize(text) -> list`；`close()`。

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_normative_encoder.py`（patch `sentence_transformers`，仿 `test_retriever.py` 的 fake 注入）：
```python
import sys
import types
import unittest

import numpy as np


class FakeSentenceTransformer:
    def __init__(self, model_path):
        self._model_path = str(model_path)

    def encode(self, texts, convert_to_numpy=True):
        return np.random.RandomState(0).rand(len(texts), 4)

    def tokenize(self, text):
        return text.split(" ")


sys.modules["sentence_transformers"] = types.SimpleNamespace(
    SentenceTransformer=FakeSentenceTransformer
)

from kg_extract_build.normative_encoder import (
    EncoderProfile,
    NormativeEncoder,
    build_encoder_profile_hash,
    model_revision,
)


class EncoderTests(unittest.TestCase):
    def test_profile_hash_stable_and_sensitive(self):
        p = EncoderProfile("model-a", "rev-1", 384, "查询：", "条款：")
        self.assertEqual(build_encoder_profile_hash(p), build_encoder_profile_hash(p))
        q = EncoderProfile("model-a", "rev-2", 384, "查询：", "条款：")
        self.assertNotEqual(build_encoder_profile_hash(p), build_encoder_profile_hash(q))

    def test_encoder_applies_prefix_and_normalizes(self):
        encoder = NormativeEncoder("fake", EncoderProfile("model-a", "rev-1", 4, "查询：", "条款：", normalize=True))
        vec = encoder.encode_query("通风")
        self.assertEqual(vec.shape, (4,))
        norm = float(np.linalg.norm(vec))
        self.assertAlmostEqual(norm, 1.0, places=5)
        self.assertTrue(bool(vec.tolist()))
        encoder.close()

    def test_encoder_document_prefix_visible_to_model(self):
        captured = {}

        class CapturingTransformer(FakeSentenceTransformer):
            def encode(self, texts, convert_to_numpy=True):
                captured["texts"] = list(texts)
                return super().encode(texts, convert_to_numpy=True)

        sys.modules["sentence_transformers"] = types.SimpleNamespace(
            SentenceTransformer=CapturingTransformer
        )
        encoder = NormativeEncoder("fake", EncoderProfile("model-a", "rev-1", 4, "查询：", "条款："))
        encoder.encode_documents(["通风"])
        self.assertIn("条款：", captured["texts"][0])

    def test_model_revision_deterministic(self):
        self.assertEqual(model_revision("/no/such/dir"), model_revision("/no/such/dir"))
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_encoder.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`kg_extract_build/normative_encoder.py`：
```python
"""规范向量编码器：冻结 encoder_profile，查询与文档编码一致。"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .normative import stable_hash


@dataclass(frozen=True)
class EncoderProfile:
    embedding_model_key: str
    embedding_model_revision: str
    embedding_dimension: int
    query_prefix: str = ""
    document_prefix: str = ""
    pooling: str = "mean"
    normalize: bool = True
    max_input_tokens: int = 128


def build_encoder_profile_hash(profile: EncoderProfile) -> str:
    return stable_hash(
        {
            "model_key": profile.embedding_model_key,
            "model_revision": profile.embedding_model_revision,
            "dimension": profile.embedding_dimension,
            "query_prefix": profile.query_prefix,
            "document_prefix": profile.document_prefix,
            "pooling": profile.pooling,
            "normalize": profile.normalize,
            "max_input_tokens": profile.max_input_tokens,
        }
    )


def model_revision(model_path) -> str:
    path = Path(str(model_path))
    if not path.exists():
        return hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    digest = hashlib.sha256()
    files = sorted(p for p in path.rglob("*") if p.is_file())
    for file_path in files:
        digest.update(str(file_path).encode("utf-8"))
        try:
            digest.update(file_path.read_bytes()[:4096])
        except OSError:
            pass
    return digest.hexdigest()


def _encode(model, texts, prefix, normalize):
    texts = [f"{prefix}{text}" if prefix else text for text in texts]
    vectors = model.encode(texts, convert_to_numpy=True)
    if normalize:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms
    return vectors


class NormativeEncoder:
    def __init__(self, model_path, profile: EncoderProfile):
        self._profile = profile
        self._model = None
        self._model_path = model_path

    def _lazy(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except Exception as exc:
                raise RuntimeError(
                    "无法加载 sentence-transformers，请检查依赖" 
                ) from exc
            self._model = SentenceTransformer(str(self._model_path))
        return self._model

    def encode_documents(self, texts):
        return _encode(self._lazy(), texts, self._profile.document_prefix, self._profile.normalize)

    def encode_query(self, text):
        return _encode(self._lazy(), [text], self._profile.query_prefix, self._profile.normalize)[0]

    def tokenize(self, text):
        tokenizer = getattr(self._lazy(), "tokenize", None)
        if tokenizer is None:
            return str(text).split()
        return tokenizer(text)

    def close(self):
        self._model = None
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_encoder.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/normative_encoder.py kg_extract_build/tests/test_normative_encoder.py
git commit -m "feat: MiniLM 规范编码器与 encoder_profile 冻结"
```

---

### Task 7: Milvus 集合族封装

**Files:**
- Create: `kg_extract_build/normative_vector_store.py`
- Test: `kg_extract_build/tests/test_normative_vector_store.py`

**Interfaces:**
- Consumes: `normative_encoder.EncoderProfile`。
- Produces:
  - `class NormativeMilvusStore`：`__init__(uri, token="", collection_prefix="kg_normative_clauses")`（懒导入 pymilvus）；`collection_name(profile) -> str`（`f"{prefix}__{slug}__v{major}"`，`slug` 由 `embedding_model_key` + 维度生成 `minilm_384`）；`ensure_collection(profile) -> None`（维度与已有集合不一致时抛 `ValueError`，一致才建）；`upsert_segments(profile, records: list[dict]) -> None`（records 含 `segment_id/index_id/clause_id/clause_set_id/version_id/family_id/document_id/source_type/clause_number/text_hash/embedding`）；`search(profile, query_vector, index_ids: list[str], version_ids: list[str], limit: int) -> list[dict]`；`close()`。
  - `build_normative_vector_store() -> NormativeMilvusStore`（读 settings，NORM_MILVUS_ENABLED=False 时返回 `NullNormativeVectorStore`）。

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_normative_vector_store.py`：
```python
import unittest

from kg_extract_build.normative_encoder import EncoderProfile
from kg_extract_build.normative_vector_store import NormativeMilvusStore

MINILM = EncoderProfile("paraphrase-multilingual-MiniLM-L12-v2", "rev", 384)


class FakeMilvusClient:
    def __init__(self, **kwargs):
        self.collections = set()
        self.upserted = []
        self.searched = None

    def has_collection(self, collection_name):
        return collection_name in self.collections

    def create_collection(self, collection_name, dimension, **kwargs):
        if collection_name in self.collections:
            raise ValueError(f"exists {collection_name}")
        self.collections.add(collection_name)
        self.dimension = dimension

    def upsert(self, collection_name, data):
        self.upserted.extend(data)

    def search(self, collection_name, data, filter="", limit=10, output_fields=None, anns_field="embedding"):
        self.searched = dict(collection_name=collection_name, data=data, filter=filter, limit=limit)
        return [[{"entity": {"clause_id": 1, "version_id": "v1", "index_id": "i1"},
                  "distance": 0.9} for _ in range(limit)]]

    def close(self):
        pass


class NormativeVectorStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = NormativeMilvusStore("http://x", collection_prefix="kg_normative_clauses")
        self.store.client = FakeMilvusClient()

    def test_collection_name_uses_model_and_dimension(self):
        self.assertEqual(
            self.store.collection_name(MINILM),
            "kg_normative_clauses__minilm_384__v1",
        )

    def test_dimension_mismatch_rejected(self):
        self.store.ensure_collection(MINILM)
        other = EncoderProfile("paraphrase-multilingual-MiniLM-L12-v2", "rev", 512)
        with self.assertRaises(ValueError):
            self.store.ensure_collection(other)

    def test_upsert_and_search_pass_stable_ids(self):
        profile = MINILM
        self.store.ensure_collection(profile)
        self.store.upsert_segments(profile, [{
            "segment_id": 1, "index_id": "idx-1", "clause_id": 501,
            "clause_set_id": "set-1", "version_id": "v1", "family_id": "f1",
            "document_id": 36, "source_type": "spec", "clause_number": "第二十条",
            "text_hash": "h", "embedding": [0.1] * 384,
        }])
        hits = self.store.search(profile, [0.1] * 384, ["idx-1"], ["v1"], limit=10)
        self.assertEqual(hits[0]["clause_id"], 1)
        self.assertIn("idx-1", self.store.client.searched["filter"])
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_vector_store.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`kg_extract_build/normative_vector_store.py`：
```python
"""规范条款 Milvus 集合族封装（维度隔离，只存稳定标识+向量）。"""

from __future__ import annotations

import os
import re

from . import settings


def _slug(model_key: str, dimension: int) -> str:
    match = re.search(r"minilm|qwen3|bge-?m3", model_key, re.IGNORECASE)
    base = (match.group(0).lower().replace("-", "") if match else "model")
    return f"{base}_{dimension}"


class NormativeMilvusStore:
    def __init__(self, uri, token="", collection_prefix="kg_normative_clauses"):
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:
            raise RuntimeError("启用规范向量索引需要安装 pymilvus") from exc
        options = {"uri": uri}
        if token:
            options["token"] = token
        self.client = MilvusClient(**options)
        self.collection_prefix = collection_prefix

    @classmethod
    def from_env(cls):
        return cls(
            uri=settings.NORM_MILVUS_URI,
            token=settings.NORM_MILVUS_TOKEN,
            collection_prefix=settings.NORM_MILVUS_COLLECTION_PREFIX,
        )

    def collection_name(self, profile) -> str:
        return f"{self.collection_prefix}__{_slug(profile.embedding_model_key, profile.embedding_dimension)}__v1"

    def ensure_collection(self, profile) -> None:
        name = self.collection_name(profile)
        if self.client.has_collection(collection_name=name):
            info = self.client.describe_collection(name)
            if int(info.get("params", {}).get("dimension", 0)) != profile.embedding_dimension:
                raise ValueError(f"集合 {name} 维度与 {profile.embedding_dimension} 不匹配")
            return
        self.client.create_collection(
            collection_name=name,
            dimension=profile.embedding_dimension,
            primary_field_name="segment_id",
            vector_field_name="embedding",
            metric_type="COSINE",
            auto_id=False,
            enable_dynamic_field=True,
        )

    def upsert_segments(self, profile, records) -> None:
        if not records:
            return
        self.ensure_collection(profile)
        self.client.upsert(
            collection_name=self.collection_name(profile),
            data=records,
        )

    def search(self, profile, query_vector, index_ids, version_ids, limit=30):
        name = self.collection_name(profile)
        filters = []
        if index_ids:
            ids = ",".join(f'"{i}"' for i in index_ids)
            filters.append(f"index_id in [{ids}]")
        if version_ids:
            ids = ",".join(f'"{v}"' for v in version_ids)
            filters.append(f"version_id in [{ids}]")
        filter_expr = " and ".join(filters)
        results = self.client.search(
            collection_name=name,
            data=[query_vector],
            filter=filter_expr,
            limit=int(limit),
            anns_field="embedding",
            output_fields=[
                "index_id", "clause_id", "clause_set_id", "version_id",
                "family_id", "document_id", "source_type", "clause_number", "text_hash",
            ],
        )
        hits = []
        for row in results[0]:
            entity = row.get("entity") or {}
            hits.append(
                {**entity, "score": float(row.get("distance", 0.0))}
            )
        return hits

    def close(self):
        close = getattr(self.client, "close", None)
        if callable(close):
            close()


class NullNormativeVectorStore:
    enabled = False

    def ensure_collection(self, profile):
        return None

    def upsert_segments(self, profile, records):
        return None

    def search(self, profile, query_vector, index_ids, version_ids, limit=30):
        return []

    def close(self):
        return None


def build_normative_vector_store():
    if not settings.NORM_MILVUS_ENABLED:
        return NullNormativeVectorStore()
    return NormativeMilvusStore.from_env()
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_vector_store.py -v`
Expected: PASS（FakeMilvusClient 需补 `describe_collection` 与 `get`，若断言报 AttributeError 则在 fake 中补 `def describe_collection(self, collection_name): return {"params": {"dimension": 384}}`）

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/normative_vector_store.py kg_extract_build/tests/test_normative_vector_store.py
git commit -m "feat: 规范条款 Milvus 集合族封装"
```

---

### Task 8: 索引构建与重建（幂等指纹 + 状态机）

**Files:**
- Create: `kg_extract_build/normative_indexer.py`
- Test: `kg_extract_build/tests/test_normative_indexer.py`

**Interfaces:**
- Consumes: `NormativeStore`（`get_version/get_clauses/save_index/save_segments/get_index_by_fingerprint`）、`NormativeMilvusStore`、`NormativeEncoder`、`EncoderProfile`、`build_index_fingerprint`、`build_encoder_profile_hash`、`segment_clause`、`stable_hash`。
- Produces:
  - `class NormativeIndexer`：`__init__(store, vector_store, encoder, profile)`。
  - `build_index(version_id: str) -> dict`：返回 `{"status": "skipped"|"ready"|"failed", "index_id": str | None, "reason": str}`。逻辑：读版本与条款→空则 `failed`；算指纹→已存在则 `skipped`；分段+编码+`upsert_segments`+落 `kg_normative_index`(status=ready) 与 `kg_normative_index_segment`；异常置 `failed` 并写 `error_message`，不抛出。
  - `build_release(release_name: str, index_ids: list[str]) -> str`：新建 `published` 发布版并登记 member，返回 `release_id`。

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_normative_indexer.py`：
```python
import unittest
from types import SimpleNamespace

from kg_extract_build.normative_indexer import NormativeIndexer

from test_normative_persistence import InMemoryBackend


class FakeNormativeVectorStore:
    def __init__(self):
        self.records = []

    def ensure_collection(self, profile):
        return None

    def collection_name(self, profile):
        return f"kg_normative_clauses__minilm_384__v1"

    def upsert_segments(self, profile, records):
        self.records.extend(records)

    def search(self, profile, query_vector, index_ids, version_ids, limit=30):
        return []

    def close(self):
        pass


class FakeEncoder:
    def __init__(self):
        self.encoded = []

    def encode_documents(self, texts):
        self.encoded.extend(texts)
        return [[0.1] * 384 for _ in texts]

    def encode_query(self, text):
        return [0.1] * 384

    def tokenize(self, text):
        return text.split(" ")

    def close(self):
        pass


def make_store(version_rows, clause_rows):
    backend = InMemoryBackend()
    for row in version_rows:
        backend.rows["kg_normative_version"].append(row)
    backend.rows["kg_normative_clause"] = clause_rows
    clause_set_id = clause_rows[0]["clause_set_id"] if clause_rows else "set-1"
    return SimpleNamespace(
        _backend=backend,
        get_version=lambda vid: next((r for r in version_rows if r["version_id"] == vid), None),
        latest_clause_set=lambda vid: {"clause_set_id": clause_set_id},
        get_clauses=lambda cid: [r for r in clause_rows if r.get("clause_set_id") == cid],
        save_index=lambda record: backend.rows.setdefault("kg_normative_index", []).append(record),
        save_segments=lambda index_id, segs: backend.rows.setdefault("segments", []).extend(segs),
        get_index_by_fingerprint=lambda fp: next((r for r in backend.rows.get("kg_normative_index", []) if r["index_fingerprint"] == fp), None),
    )


class IndexerTests(unittest.TestCase):
    def test_build_index_ready_and_persists(self):
        store = make_store(
            [{"version_id": "v1", "family_id": "f1", "document_id": 36,
              "effective_year": 2020, "invalid_year": None,
              "metadata_confirmed": True, "status": "effective"}],
            [{"clause_set_id": "set-1", "clause_number": "第二十条",
              "raw_text": "作业前应通风。", "normalized_text": "作业前应通风。",
              "start_offset": 0, "end_offset": 8, "content_hash": "h",
              "parse_status": "structured", "hierarchy_path": ["总则"]}],
        )
        encoder = FakeEncoder()
        indexer = NormativeIndexer(
            store, FakeNormativeVectorStore(), encoder,
            SimpleNamespace(embedding_model_key="minilm", embedding_model_revision="r",
                            embedding_dimension=384, max_input_tokens=128,
                            document_prefix="", query_prefix="", normalize=True),
        )
        result = indexer.build_index("v1")
        self.assertEqual(result["status"], "ready")
        self.assertTrue(encoder.encoded)

    def test_build_index_skips_when_fingerprint_exists(self):
        store = make_store(
            [{"version_id": "v1", "family_id": "f1", "document_id": 36,
              "effective_year": 2020, "invalid_year": None,
              "metadata_confirmed": True, "status": "effective"}],
            [{"clause_set_id": "set-1", "clause_number": "第二十条",
              "raw_text": "作业前应通风。", "normalized_text": "作业前应通风。",
              "start_offset": 0, "end_offset": 8, "content_hash": "h",
              "parse_status": "structured", "hierarchy_path": ["总则"]}],
        )
        store._backend.rows["kg_normative_index"] = [{"index_fingerprint": "fp", "index_id": "idx-0"}]
        indexer = NormativeIndexer(store, FakeNormativeVectorStore(), FakeEncoder(), SimpleNamespace(
            embedding_model_key="minilm", embedding_model_revision="r",
            embedding_dimension=384, max_input_tokens=128,
            document_prefix="", query_prefix="", normalize=True))
        result = indexer.build_index("v1")
        self.assertEqual(result["status"], "skipped")

    def test_build_index_failed_when_no_clauses(self):
        store = make_store(
            [{"version_id": "v1", "family_id": "f1", "document_id": 36,
              "effective_year": 2020, "invalid_year": None,
              "metadata_confirmed": True, "status": "effective"}],
            [],
        )
        indexer = NormativeIndexer(store, FakeNormativeVectorStore(), FakeEncoder(), SimpleNamespace(
            embedding_model_key="minilm", embedding_model_revision="r",
            embedding_dimension=384, max_input_tokens=128,
            document_prefix="", query_prefix="", normalize=True))
        result = indexer.build_index("v1")
        self.assertEqual(result["status"], "failed")
        self.assertIn("条款", result["reason"])
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_indexer.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`kg_extract_build/normative_indexer.py`：
```python
"""规范索引构建/重建：幂等指纹 + 状态机，失败不影响三元组实验。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .normative import build_index_fingerprint, stable_hash
from .normative_encoder import build_encoder_profile_hash
from .normative_persistence import NormativeStore
from .normative_segmentation import SegmentDraft, segment_clause


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


class NormativeIndexer:
    def __init__(self, store: NormativeStore, vector_store, encoder, profile):
        self.store = store
        self.vector_store = vector_store
        self.encoder = encoder
        self.profile = profile

    def build_index(self, version_id: str) -> dict:
        version = self.store.get_version(version_id)
        if version is None:
            return {"status": "failed", "index_id": None, "reason": f"版本不存在：{version_id}"}
        clause_set = self.store.latest_clause_set(version_id)
        if clause_set is None:
            return {"status": "failed", "index_id": None, "reason": "版本未解析出条款集，无法构建索引"}
        clauses = self.store.get_clauses(clause_set["clause_set_id"])
        if not clauses:
            return {"status": "failed", "index_id": None, "reason": "条款解析为空，无法构建索引"}

        clause_set_id = clause_set["clause_set_id"]
        fingerprint = build_index_fingerprint(
            document_content_hash=stable_hash({"doc": version["document_id"]}),
            metadata_hash=version["metadata_hash"],
            clause_set_id=clause_set_id,
            chunk_config={"max_tokens": self.profile.max_input_tokens, "overlap": 8},
            embedding_model_revision=self.profile.embedding_model_revision,
            encoder_profile_hash=build_encoder_profile_hash(self.profile),
            embedding_dimension=self.profile.embedding_dimension,
        )
        existing = self.store.get_index_by_fingerprint(fingerprint)
        if existing is not None:
            return {"status": "skipped", "index_id": existing["index_id"], "reason": "指纹幂等，跳过重建"}

        index_id = str(uuid.uuid4())
        try:
            segments = self._build_segments(version, clauses)
            texts = [draft.embedding_text for _, draft in segments]
            embeddings = self.encoder.encode_documents(texts)
            records = self._build_records(version, clauses, segments, index_id, embeddings)
            self.vector_store.ensure_collection(self.profile)
            self.vector_store.upsert_segments(self.profile, records)
            self.store.save_index(
                {
                    "index_id": index_id, "version_id": version_id,
                    "clause_set_id": clause_set_id,
                    "collection_name": self.vector_store.collection_name(self.profile),
                    "embedding_model_key": self.profile.embedding_model_key,
                    "embedding_model_revision": self.profile.embedding_model_revision,
                    "embedding_dimension": self.profile.embedding_dimension,
                    "encoder_profile_hash": build_encoder_profile_hash(self.profile),
                    "metric_type": "COSINE",
                    "chunker_version": "normative-clause-v1",
                    "chunk_config_json": {"max_tokens": self.profile.max_input_tokens, "overlap": 8},
                    "index_fingerprint": fingerprint,
                    "status": "ready",
                    "error_message": None,
                }
            )
            self.store.save_segments(index_id, segments)
            return {"status": "ready", "index_id": index_id, "reason": ""}
        except Exception as exc:
            self.store.save_index(
                {
                    "index_id": index_id, "version_id": version_id,
                    "clause_set_id": clause_set_id,
                    "collection_name": self.vector_store.collection_name(self.profile),
                    "embedding_model_key": self.profile.embedding_model_key,
                    "embedding_model_revision": self.profile.embedding_model_revision,
                    "embedding_dimension": self.profile.embedding_dimension,
                    "encoder_profile_hash": build_encoder_profile_hash(self.profile),
                    "metric_type": "COSINE",
                    "chunker_version": "normative-clause-v1",
                    "chunk_config_json": {"max_tokens": self.profile.max_input_tokens, "overlap": 8},
                    "index_fingerprint": fingerprint,
                    "status": "failed",
                    "error_message": str(exc),
                }
            )
            return {"status": "failed", "index_id": index_id, "reason": str(exc)}

    def _build_segments(self, version, clauses):
        family_name = version.get("display_name") or version["version_id"]
        segments = []
        for clause in clauses:
            segment_drafts = segment_clause(
                _to_clause_draft(clause),
                family_name=family_name,
                tokenizer=self.encoder.tokenize,
                max_tokens=self.profile.max_input_tokens,
                overlap_tokens=8,
            )
            for draft in segment_drafts:
                segments.append((clause, draft))
        return segments

    def _build_records(self, version, clauses, segments, index_id, embeddings):
        records = []
        for (clause, draft), embedding in zip(segments, embeddings):
            records.append(
                {
                    "segment_id": draft.text_hash[:16],
                    "index_id": index_id,
                    "clause_id": clause["clause_id"],
                    "clause_set_id": clause["clause_set_id"],
                    "version_id": version["version_id"],
                    "family_id": version["family_id"],
                    "document_id": version["document_id"],
                    "source_type": "spec",
                    "clause_number": clause["clause_number"],
                    "text_hash": draft.text_hash,
                    "embedding": embedding,
                }
            )
        return records

    def build_release(self, release_name: str, index_ids: list[str]) -> str:
        release_id = str(uuid.uuid4())
        self.store.save_release(
            {
                "release_id": release_id,
                "release_name": release_name,
                "collection_name": self.vector_store.collection_name(self.profile),
                "embedding_model_key": self.profile.embedding_model_key,
                "embedding_model_revision": self.profile.embedding_model_revision,
                "encoder_profile_hash": build_encoder_profile_hash(self.profile),
                "release_fingerprint": stable_hash({"name": release_name, "index_ids": sorted(index_ids)}),
                "status": "published",
            }
        )
        for row in self.store.index_rows(index_ids):
            self.store.save_release_member(
                release_id, row["index_id"], row["version_id"], row["clause_set_id"],
            )
        return release_id


def _to_clause_draft(row: dict):
    from .normative import ClauseDraft
    return ClauseDraft(
        clause_number=row.get("clause_number"),
        hierarchy_path=tuple(row.get("hierarchy_path") or ()),
        clause_title=row.get("clause_title"),
        raw_text=row.get("raw_text") or "",
        normalized_text=row.get("normalized_text") or "",
        start_offset=row.get("start_offset") or 0,
        end_offset=row.get("end_offset") or 0,
        parse_status=row.get("parse_status") or "fallback",
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_indexer.py -v`
Expected: PASS（需在 `NormativeStore` 增加 `save_index/save_segments/get_index_by_fingerprint/save_release/save_release_member` 薄方法；若报缺少方法，在 Task 8 内补上并同步回 Task 3 的接口定义——见下方实现补充）

**实现补充（并入 `normative_persistence.py`）**：为 `NormativeStore` 追加：
```python
    def latest_clause_set(self, version_id: str) -> dict | None:
        rows = self._backend._read(
            "SELECT * FROM kg_normative_clause_set "
            "WHERE version_id=%s AND status='published' "
            "ORDER BY created_at DESC LIMIT 1",
            (version_id,),
        )
        return rows[0] if rows else None

    def save_index(self, record: dict) -> None:
        import json
        self._backend._write(
            "INSERT INTO kg_normative_index "
            "(index_id, version_id, clause_set_id, collection_name, embedding_model_key, "
            " embedding_model_revision, embedding_dimension, encoder_profile_hash, "
            " metric_type, chunker_version, chunk_config_json, index_fingerprint, "
            " status, error_message, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (record["index_id"], record["version_id"], record["clause_set_id"],
             record["collection_name"], record["embedding_model_key"],
             record["embedding_model_revision"], record["embedding_dimension"],
             record["encoder_profile_hash"], record["metric_type"],
             record["chunker_version"],
             json.dumps(record.get("chunk_config_json") or {}, ensure_ascii=False),
             record["index_fingerprint"], record["status"],
             record.get("error_message"), _utc_now()),
        )

    def get_index_by_fingerprint(self, fingerprint: str) -> dict | None:
        rows = self._backend._read(
            "SELECT * FROM kg_normative_index WHERE index_fingerprint=%s", (fingerprint,)
        )
        return rows[0] if rows else None

    def save_segments(self, index_id: str, segments) -> None:
        params = [
            (index_id, clause_row["clause_id"], draft.segment_index,
             draft.embedding_text, draft.token_count, draft.text_hash,
             draft.text_hash[:16], _utc_now())
            for clause_row, draft in segments
        ]
        self._backend._write(
            "INSERT INTO kg_normative_index_segment "
            "(index_id, clause_id, segment_index, embedding_text, token_count, "
            " text_hash, milvus_vector_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            params, many=True,
        )

    def save_release(self, record: dict) -> None:
        self._backend._write(
            "INSERT INTO kg_normative_index_release "
            "(release_id, release_name, collection_name, embedding_model_key, "
            " embedding_model_revision, encoder_profile_hash, release_fingerprint, "
            " status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (record["release_id"], record["release_name"], record["collection_name"],
             record["embedding_model_key"], record["embedding_model_revision"],
             record["encoder_profile_hash"], record["release_fingerprint"],
             record["status"], _utc_now()),
        )

    def save_release_member(self, release_id: str, index_id: str, version_id: str, clause_set_id: str) -> None:
        self._backend._write(
            "INSERT INTO kg_normative_index_release_member "
            "(release_id, index_id, version_id, clause_set_id, included_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (release_id, index_id, version_id, clause_set_id, _utc_now()),
        )

    def release_member_index_ids(self, release_id: str) -> list[str]:
        rows = self._backend._read(
            "SELECT index_id FROM kg_normative_index_release_member WHERE release_id=%s",
            (release_id,),
        )
        return [r["index_id"] for r in rows]

    def index_rows(self, index_ids: list[str]) -> list[dict]:
        if not index_ids:
            return []
        placeholders = ",".join(["%s"] * len(index_ids))
        return self._backend._read(
            f"SELECT * FROM kg_normative_index WHERE index_id IN ({placeholders})", list(index_ids)
        )
```

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/normative_indexer.py kg_extract_build/normative_persistence.py kg_extract_build/tests/test_normative_indexer.py
git commit -m "feat: 规范索引构建与发布版（幂等指纹+状态机）"
```

---

### Task 9: 覆盖状态计算

**Files:**
- Create: `kg_extract_build/normative_coverage.py`
- Test: `kg_extract_build/tests/test_normative_coverage.py`

**Interfaces:**
- Consumes: `applicable_versions`、`NormativeVersionCandidate`。
- Produces:
  - `compute_coverage(candidates_by_family: dict[str, list[NormativeVersionCandidate]], version_index_map: dict[str, str], requested_families: list[str], conflicts: dict[str, bool]) -> list[dict]`：每项声明规范返回 `{"family_id", "coverage_status", "candidate_version_ids", "same_year_version_conflict", "warnings"}`；`covered`=全部候选有索引、`partial`=部分、`cited_but_unindexed`=有候选但无索引、`uncovered`=无候选。

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_normative_coverage.py`：
```python
import unittest

from kg_extract_build.normative import NormativeVersionCandidate
from kg_extract_build.normative_coverage import compute_coverage


def v(vid, family, year=2020, invalid=None, confirmed=True, status="effective"):
    return NormativeVersionCandidate(vid, family, year, invalid, confirmed, status)


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.families = {
            "f1": [v("v1", "f1"), v("v2", "f1", 2025)],
            "f2": [v("v3", "f2")],
        }

    def test_covered_when_all_candidates_indexed(self):
        result = compute_coverage(self.families, {"v1": "i1", "v2": "i2"}, ["f1"], {})
        self.assertEqual(result[0]["coverage_status"], "covered")
        self.assertEqual(result[0]["candidate_version_ids"], ["v1", "v2"])

    def test_partial_when_some_indexed(self):
        result = compute_coverage(self.families, {"v1": "i1"}, ["f1"], {})
        self.assertEqual(result[0]["coverage_status"], "partial")

    def test_cited_but_unindexed_when_none_indexed(self):
        result = compute_coverage(self.families, {}, ["f1"], {})
        self.assertEqual(result[0]["coverage_status"], "cited_but_unindexed")

    def test_uncovered_when_no_candidate(self):
        result = compute_coverage({"f3": []}, {}, ["f3"], {})
        self.assertEqual(result[0]["coverage_status"], "uncovered")

    def test_conflict_flag_propagates(self):
        result = compute_coverage(self.families, {"v1": "i1", "v2": "i2"}, ["f1"], {"f1": True})
        self.assertTrue(result[0]["same_year_version_conflict"])
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_coverage.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`kg_extract_build/normative_coverage.py`：
```python
"""声明规范覆盖状态计算（covered/partial/uncovered/cited_but_unindexed）。"""

from __future__ import annotations


def compute_coverage(candidates_by_family, version_index_map, requested_families, conflicts):
    coverage = []
    for family_id in requested_families:
        candidates = candidates_by_family.get(family_id, [])
        version_ids = [item.version_id for item in candidates]
        indexed = [vid for vid in version_ids if version_index_map.get(vid)]
        if not candidates:
            status = "uncovered"
        elif not indexed:
            status = "cited_but_unindexed"
        elif len(indexed) < len(version_ids):
            status = "partial"
        else:
            status = "covered"
        coverage.append(
            {
                "family_id": family_id,
                "coverage_status": status,
                "candidate_version_ids": version_ids,
                "same_year_version_conflict": bool(conflicts.get(family_id)),
                "warnings": [],
            }
        )
    return coverage
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_coverage.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/normative_coverage.py kg_extract_build/tests/test_normative_coverage.py
git commit -m "feat: 声明规范覆盖状态计算"
```

---

### Task 10: 纯向量检索（聚合去重 + 扩窗 + 完整条款回取）

**Files:**
- Create: `kg_extract_build/normative_search.py`
- Test: `kg_extract_build/tests/test_normative_search.py`

**Interfaces:**
- Consumes: `applicable_versions`、`compute_coverage`、`NormativeStore`、`NormativeMilvusStore`、`NormativeEncoder`、`EncoderProfile`。
- Produces:
  - `@dataclass(frozen=True) SearchRequest(query: str, audit_year: int, release_id: str, norm_scope: dict, top_k: int)`
  - `class NormativeSearcher`：`__init__(store, vector_store, encoder, profile)`；`search(request) -> dict`。返回 `{"coverage": [...], "evidence": [...], "retrieval_trace": {...}, "warnings": []}`；evidence 元素含 `release_id/index_id/family_id/version_id/clause_set_id/clause_id/clause_number/text/clause_content_hash/score/rank/source_type/same_year_version_conflict/hit_segment_ids`。Top-K 按条款数；segment 超额系数 `max(top_k * 3, 30)`，去重不足时翻倍扩窗直到足够、候选耗尽或达安全上限（如 300）。检索不调 Neo4j、不调 LLM。

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_normative_search.py`：
```python
import unittest

from kg_extract_build.normative import NormativeVersionCandidate
from kg_extract_build.normative_search import NormativeSearcher, SearchRequest


class FakeStore:
    def __init__(self, versions, clauses, index_map, release_members, indexes):
        self._versions = versions
        self._clauses = clauses
        self._index_map = index_map
        self._release_members = release_members
        self._indexes = indexes

    def version_candidates(self):
        return self._versions

    def release_member_index_ids(self, release_id):
        return self._release_members

    def index_rows(self, index_ids):
        return [r for r in self._indexes if r["index_id"] in index_ids]

    def get_clauses(self, clause_set_id):
        return [c for c in self._clauses if c["clause_set_id"] == clause_set_id]


class FakeVectorStore:
    def __init__(self, hits):
        self._hits = hits

    def search(self, profile, query_vector, index_ids, version_ids, limit=30):
        return self._hits[:limit]

    def close(self):
        pass


class FakeEncoder:
    def encode_query(self, text):
        return [0.1] * 4


PROFILE = {"embedding_model_key": "minilm", "embedding_dimension": 384}


class SearchTests(unittest.TestCase):
    def test_aggregates_segments_and_returns_full_clause(self):
        versions = [NormativeVersionCandidate("v1", "f1", 2020, None, True, "effective")]
        clauses = [{"clause_set_id": "set-1", "clause_id": 501, "clause_number": "第二十条",
                    "raw_text": "有限空间作业应当先通风。", "content_hash": "h1"}]
        hits = [
            {"index_id": "i1", "clause_id": 501, "version_id": "v1", "family_id": "f1",
             "clause_set_id": "set-1", "clause_number": "第二十条", "text_hash": "s1", "score": 0.9},
            {"index_id": "i1", "clause_id": 501, "version_id": "v1", "family_id": "f1",
             "clause_set_id": "set-1", "clause_number": "第二十条", "text_hash": "s2", "score": 0.7},
        ]
        store = FakeStore(versions, clauses, {"v1": "i1"}, ["i1"],
                          [{"index_id": "i1", "clause_set_id": "set-1", "version_id": "v1", "family_id": "f1"}])
        searcher = NormativeSearcher(store, FakeVectorStore(hits), FakeEncoder(), PROFILE)
        result = searcher.search(SearchRequest("通风", 2025, "rel-1", {}, top_k=1))
        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual(result["evidence"][0]["clause_id"], 501)
        self.assertEqual(result["evidence"][0]["text"], "有限空间作业应当先通风。")
        self.assertEqual(result["retrieval_trace"]["unique_clause_count"], 1)

    def test_expands_window_when_dedup_below_topk(self):
        versions = [NormativeVersionCandidate("v1", "f1", 2020, None, True, "effective")]
        clauses = [{"clause_set_id": "set-1", "clause_id": 501, "clause_number": "第二十条",
                    "raw_text": "A 条款。", "content_hash": "h1"}]
        index_rows = [{"index_id": "i1", "clause_set_id": "set-1", "version_id": "v1", "family_id": "f1"}]

        class ExpandingVectorStore(FakeVectorStore):
            def __init__(self):
                self.calls = []

            def search(self, profile, query_vector, index_ids, version_ids, limit=30):
                self.calls.append(limit)
                if limit >= 60:
                    return [{"index_id": "i1", "clause_id": 501, "version_id": "v1", "family_id": "f1",
                             "clause_set_id": "set-1", "clause_number": "第二十条", "text_hash": "s", "score": 0.5},
                            {"index_id": "i1", "clause_id": 502, "version_id": "v1", "family_id": "f1",
                             "clause_set_id": "set-1", "clause_number": "第二十一条", "text_hash": "t", "score": 0.4}]
                return [{"index_id": "i1", "clause_id": 501, "version_id": "v1", "family_id": "f1",
                         "clause_set_id": "set-1", "clause_number": "第二十条", "text_hash": "s", "score": 0.5}]
        store = FakeStore(versions, clauses, {"v1": "i1"}, ["i1"], index_rows)
        vector_store = ExpandingVectorStore()
        searcher = NormativeSearcher(store, vector_store, FakeEncoder(), PROFILE)
        result = searcher.search(SearchRequest("查询", 2025, "rel-1", {}, top_k=2))
        self.assertEqual(len(result["evidence"]), 2)
        self.assertGreater(len(vector_store.calls), 1)
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_search.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`kg_extract_build/normative_search.py`：
```python
"""纯向量检索预览：年份过滤 + 覆盖状态 + segment 聚合去重 + 扩窗。"""

from __future__ import annotations

from dataclasses import dataclass

from .normative import applicable_versions
from .normative_coverage import compute_coverage

BASE_OVERSAMPLE = 3
MIN_RAW_LIMIT = 30
MAX_RAW_LIMIT = 300


@dataclass(frozen=True)
class SearchRequest:
    query: str
    audit_year: int
    release_id: str
    norm_scope: dict
    top_k: int


class NormativeSearcher:
    def __init__(self, store, vector_store, encoder, profile):
        self.store = store
        self.vector_store = vector_store
        self.encoder = encoder
        self.profile = profile

    def search(self, request: SearchRequest) -> dict:
        index_ids = self.store.release_member_index_ids(request.release_id)
        if not index_ids:
            return {
                "coverage": [],
                "evidence": [],
                "retrieval_trace": {"raw_segment_limit": 0, "raw_segment_count": 0, "unique_clause_count": 0, "stop_reason": "release_empty"},
                "warnings": [f"发布版 {request.release_id} 无成员索引"],
            }

        scope = request.norm_scope or {}
        allowed_families = tuple(scope.get("allowed_family_ids") or ())
        allowed_versions = tuple(scope.get("allowed_version_ids") or ())
        versions = self.store.version_candidates()
        candidates, conflicts = applicable_versions(
            versions, request.audit_year, allowed_families, allowed_versions,
        )
        index_rows = self.store.index_rows(index_ids)
        index_by_version = {r["version_id"]: r for r in index_rows}
        version_index_map = {r["version_id"]: r["index_id"] for r in index_rows}

        target_versions = [v.version_id for v in candidates if v.version_id in version_index_map]

        coverage = []
        if scope.get("scope_type") == "declared":
            # 覆盖状态基于审核年份过滤后的候选版本（与原设计 §12.3 一致）
            candidates_by_family = {}
            for v in candidates:
                candidates_by_family.setdefault(v.family_id, []).append(v)
            requested = [f for f in allowed_families]
            coverage = compute_coverage(candidates_by_family, version_index_map, requested, conflicts)

        query_vector = self.encoder.encode_query(request.query)
        raw_limit = max(request.top_k * BASE_OVERSAMPLE, MIN_RAW_LIMIT)
        unique: dict[int, dict] = {}
        raw_segment_count = 0
        stop_reason = "ok"
        while raw_limit <= MAX_RAW_LIMIT:
            hits = self.vector_store.search(
                self.profile, query_vector, version_index_map and list(version_index_map.values()),
                target_versions, limit=raw_limit,
            )
            raw_segment_count += len(hits)
            for hit in hits:
                clause_id = hit.get("clause_id")
                if clause_id is None:
                    continue
                if clause_id not in unique or hit.get("score", 0) > unique[clause_id]["score"]:
                    unique[clause_id] = hit
            if len(unique) >= request.top_k or len(hits) < raw_limit:
                break
            raw_limit = min(raw_limit * 2, MAX_RAW_LIMIT)
            if raw_limit == MAX_RAW_LIMIT:
                stop_reason = "safety_cap"
                break
        if raw_segment_count and not unique:
            stop_reason = "no_hits"

        ranked = sorted(unique.values(), key=lambda r: r.get("score", 0), reverse=True)
        evidence = []
        for rank, hit in enumerate(ranked[: request.top_k], start=1):
            clause = self._fetch_clause(hit.get("clause_set_id"), hit.get("clause_id"))
            evidence.append(
                {
                    "release_id": request.release_id,
                    "index_id": hit.get("index_id"),
                    "family_id": hit.get("family_id"),
                    "version_id": hit.get("version_id"),
                    "clause_set_id": hit.get("clause_set_id"),
                    "clause_id": hit.get("clause_id"),
                    "clause_number": hit.get("clause_number"),
                    "text": clause["raw_text"] if clause else "",
                    "clause_content_hash": clause.get("content_hash") if clause else hit.get("text_hash"),
                    "score": hit.get("score", 0),
                    "rank": rank,
                    "source_type": "spec",
                    "same_year_version_conflict": bool(conflicts.get(hit.get("family_id"))),
                    "hit_segment_ids": [hit.get("text_hash")],
                }
            )

        return {
            "coverage": coverage,
            "evidence": evidence,
            "retrieval_trace": {
                "raw_segment_limit": raw_limit,
                "raw_segment_count": raw_segment_count,
                "unique_clause_count": len(unique),
                "stop_reason": stop_reason,
            },
            "warnings": [],
        }

    def _fetch_clause(self, clause_set_id, clause_id):
        if not clause_set_id:
            return None
        for row in self.store.get_clauses(clause_set_id):
            if row.get("clause_id") == clause_id:
                return row
        return None
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_search.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/normative_search.py kg_extract_build/tests/test_normative_search.py
git commit -m "feat: 规范纯向量检索（聚合去重+扩窗+完整条款回取）"
```

---

### Task 11: 规范向量索引页面

**Files:**
- Create: `kg_extract_build/dashboard_normative.py`
- Modify: `kg_extract_build/dashboard.py:633-685`（注册页面）
- Test: `kg_extract_build/tests/test_dashboard_normative.py`

**Interfaces:**
- Consumes: `MySQLExperimentStore.from_env()`、`NormativeStore`、`register_version`、`NormativeIndexer`、`NormativeEncoder`、`build_normative_vector_store`、`NormativeSearcher`、settings。
- Produces:
  - `render_normative_page()`：streamlit 页面，三个区域——①规范登记：列出 `source_type='spec'` 且 `status in ('completed','completed_empty')` 的文档，自动提取名称/年份（`guess_version_year`），表单确认后 `register_version`；②索引管理：选择已登记版本 → 构建/重建（`indexer.build_index`），新建发布版（`indexer.build_release`）；③检索预览：查询文本 + 审核年份 + 发布版 + Top-K → `searcher.search`，渲染 evidence 表格与 coverage。
  - `dashboard.py` 侧边栏新增 `NORMATIVE_PAGE = "规范向量索引"`。

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_dashboard_normative.py`（冒烟：用假 store/searcher 注入，验证 `render_normative_page` 可渲染且调用登记/构建/检索函数）：
```python
import unittest
from unittest.mock import patch

import kg_extract_build.dashboard_normative as dn


class DashboardNormativeTests(unittest.TestCase):
    def test_render_calls_search_when_form_submitted(self):
        class FakeSearcher:
            def __init__(self, *a, **k):
                self.searched = False

            def search(self, request):
                self.searched = True
                return {"coverage": [], "evidence": [], "retrieval_trace": {}, "warnings": []}

        searcher = FakeSearcher()
        with patch.object(dn.st, "form_submit_button", return_value=True), \
             patch.object(dn.st, "text_input", return_value="通风"), \
             patch.object(dn.st, "number_input", return_value=2025), \
             patch.object(dn.st, "selectbox", return_value="rel-1"), \
             patch.object(dn.st, "slider", return_value=5), \
             patch.object(dn.st, "dataframe"), patch.object(dn.st, "write"):
            dn.render_search_preview(FakeSearcher().__class__, searcher, {"rel-1": "rel-1"})
        self.assertTrue(searcher.searched)
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_dashboard_normative.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`kg_extract_build/dashboard_normative.py`：
```python
"""规范向量索引页面：登记 / 索引管理 / 检索预览。"""

from __future__ import annotations

import os

import streamlit as st

from . import settings
from .normative_encoder import EncoderProfile, NormativeEncoder, build_encoder_profile_hash, model_revision
from .normative_indexer import NormativeIndexer
from .normative_persistence import NormativeStore
from .normative_registry import guess_version_year, register_version
from .normative_search import NormativeSearcher, SearchRequest
from .normative_vector_store import build_normative_vector_store
from .persistence import MySQLExperimentStore


def _store():
    return NormativeStore(MySQLExperimentStore.from_env())


def _encoder():
    profile = EncoderProfile(
        embedding_model_key="paraphrase-multilingual-MiniLM-L12-v2",
        embedding_model_revision=model_revision(settings.NORM_VECTOR_MODEL_PATH),
        embedding_dimension=384,
        query_prefix="",
        document_prefix="",
        max_input_tokens=128,
    )
    return profile, NormativeEncoder(settings.NORM_VECTOR_MODEL_PATH, profile)


def _spec_documents():
    store = MySQLExperimentStore.from_env()
    rows = store._read(
        "SELECT document_id, file_name, status FROM kg_document "
        "WHERE source_type='spec' AND status IN ('completed', 'completed_empty')"
    )
    return rows


def render_registration_area(store):
    st.subheader("① 规范登记")
    documents = _spec_documents()
    if not documents:
        st.info("暂无已完成的规范文档。请先在'运行实验'页以'规范文件'来源处理文档。")
        return
    options = {f"{d['file_name']}（doc {d['document_id']}）": d for d in documents}
    selected = st.selectbox("选择规范文档", list(options))
    document = options[selected]
    with st.form("register_version_form"):
        display_name = st.text_input("规范名称", value=document["file_name"])
        year = st.number_input("生效年份", min_value=2000, max_value=2100, value=2025)
        status = st.selectbox("状态", ["pending_confirmation", "effective", "superseded", "repealed", "unknown"])
        if st.form_submit_button("登记版本并解析条款"):
            content = _document_content(document["document_id"])
            result = register_version(
                store, document_id=document["document_id"], file_name=document["file_name"],
                content=content, display_name=display_name, effective_year=int(year),
                status=status,
            )
            st.success(f"登记完成：条款 {result['clause_count']} 条，条款集 {result['clause_set_id']}")


def _document_content(document_id):
    store = MySQLExperimentStore.from_env()
    rows = store._read("SELECT content FROM kg_document WHERE document_id=%s", (document_id,))
    return rows[0]["content"] if rows else ""


def render_index_area(store, profile, encoder):
    st.subheader("② 索引管理")
    versions = store.list_versions()
    if not versions:
        st.info("请先在①登记规范版本。")
        return
    options = {f"{v['display_name']}（{v['version_id']}）": v for v in versions}
    selected = st.selectbox("选择版本", list(options))
    version = options[selected]
    if st.button("构建 / 重建索引"):
        indexer = NormativeIndexer(store, build_normative_vector_store(), encoder, profile)
        result = indexer.build_index(version["version_id"])
        st.write(result)
    release_name = st.text_input("发布版名称")
    if st.button("创建发布版"):
        indexer = NormativeIndexer(store, build_normative_vector_store(), encoder, profile)
        index_rows = store.index_rows([r["index_id"] for r in store._read(
            "SELECT index_id FROM kg_normative_index WHERE version_id=%s AND status='ready'",
            (version["version_id"],),
        )])
        release_id = indexer.build_release(release_name or "mvp-release", [r["index_id"] for r in index_rows])
        st.success(f"发布版：{release_id}")


def render_search_preview(searcher_class, searcher, releases):
    st.subheader("③ 检索预览")
    query = st.text_input("查询文本")
    year = st.number_input("审核年份", min_value=2000, max_value=2100, value=2025)
    release_id = st.selectbox("规范索引发布版", list(releases))
    top_k = st.slider("Top-K（条款数）", 1, 20, 5)
    if st.form_submit_button("检索"):
        result = searcher.search(SearchRequest(query, int(year), release_id, {}, int(top_k)))
        st.dataframe(result["evidence"])
        st.write(result["coverage"])
        st.write(result["retrieval_trace"])


def render_normative_page():
    if not settings.NORM_MILVUS_ENABLED:
        st.warning("KG_NORM_MILVUS_ENABLED 未开启，检索预览不可用。请在 .env 开启并启动 Milvus 服务。")
    store = _store()
    profile, encoder = _encoder()
    render_registration_area(store)
    render_index_area(store, profile, encoder)
    releases = {r["release_id"]: r["release_name"] for r in store._read(
        "SELECT release_id, release_name FROM kg_normative_index_release WHERE status='published'"
    )}
    searcher = NormativeSearcher(store, build_normative_vector_store(), encoder, profile)
    render_search_preview(NormativeSearcher, searcher, releases)
    encoder.close()
```

`kg_extract_build/dashboard.py` 修改：
```python
from kg_extract_build.dashboard_normative import render_normative_page
...
NORMATIVE_PAGE = "规范向量索引"
# radio 列表加入 NORMATIVE_PAGE
# 分发：
if page == RUN_PAGE:
    render_run_page()
elif page == AUDIT_PAGE:
    render_audit_page()
elif page == EVALUATION_PAGE:
    render_evaluation_page()
elif page == NORMATIVE_PAGE:
    render_normative_page()
else:
    ...
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_dashboard_normative.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/dashboard_normative.py kg_extract_build/dashboard.py kg_extract_build/tests/test_dashboard_normative.py
git commit -m "feat: 规范向量索引页面（登记/索引/检索三区域）"
```

---

### Task 12: 证据生命周期保护

**Files:**
- Modify: `kg_extract_build/dashboard.py:151-182`（`delete_run_with_vectors`）
- Modify: `kg_extract_build/persistence.py`（`MySQLExperimentStore` 增 `run_document_ids(run_id)`）
- Test: `kg_extract_build/tests/test_lifecycle_protection.py`

**Interfaces:**
- Consumes: `NormativeStore.has_normative_references`、`MySQLExperimentStore.run_document_ids`。
- Produces: `delete_run_with_vectors(config, run_id)` 在被引用时返回 `DeletionResult(False, "normative_referenced", "该批次包含已被规范版本/条款集/发布版引用的文档，禁止物理删除，只允许归档。")`，且**不做任何删除**（不删向量、不删 SQL）。

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/test_lifecycle_protection.py`：
```python
import unittest
from unittest.mock import patch

from kg_extract_build import dashboard


class LifecycleProtectionTests(unittest.TestCase):
    def test_delete_blocked_when_normative_referenced(self):
        config = {"host": "h", "port": 1, "user": "u", "password": "p", "database": "d", "charset": "utf8mb4"}

        class FakeStore:
            def get_deletion_state(self, run_id):
                return "active"

            def run_document_ids(self, run_id):
                return [36]

        class FakeNormStore:
            def has_normative_references(self, document_id):
                return document_id == 36

        with patch.object(dashboard, "MySQLExperimentStore", return_value=FakeStore()), \
             patch.object(dashboard, "NormativeStore", return_value=FakeNormStore()):
            result = dashboard.delete_run_with_vectors(config, "run-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.state, "normative_referenced")
        self.assertIn("只允许归档", result.message)

    def test_delete_proceeds_when_no_references(self):
        config = {"host": "h", "port": 1, "user": "u", "password": "p", "database": "d", "charset": "utf8mb4"}

        class FakeStore:
            def get_deletion_state(self, run_id):
                return "active"

            def run_document_ids(self, run_id):
                return [36]

            def mark_vectors_deleted_sql_pending(self, run_id):
                return True

            def delete_run(self, run_id):
                return True

        class FakeNormStore:
            def has_normative_references(self, document_id):
                return False

        with patch.object(dashboard, "MySQLExperimentStore", return_value=FakeStore()), \
             patch.object(dashboard, "NormativeStore", return_value=FakeNormStore()), \
             patch.object(dashboard, "build_vector_store"):
            result = dashboard.delete_run_with_vectors(config, "run-1")
        self.assertTrue(result.ok)
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_lifecycle_protection.py -v`
Expected: FAIL（`dashboard.delete_run_with_vectors` 无规范引用检查）

- [ ] **Step 3: 实现**

`kg_extract_build/persistence.py` 的 `MySQLExperimentStore` 追加：
```python
    def run_document_ids(self, run_id):
        rows = self._read(
            "SELECT document_id FROM kg_document WHERE run_id=%s", (run_id,)
        )
        return [row["document_id"] for row in rows]
```

`kg_extract_build/dashboard.py` 修改 `delete_run_with_vectors`：
```python
from kg_extract_build.normative_persistence import NormativeStore

def delete_run_with_vectors(config: dict, run_id: str) -> DeletionResult:
    """删除批次前先检查规范证据引用；被引用则拒绝删除（只允许归档）。"""
    store = _experiment_store(config)
    state = store.get_deletion_state(run_id)
    if state is None:
        return DeletionResult(False, "missing", "未找到实验批次。")
    if state != "active":
        return DeletionResult(False, state, "批次删除已进入恢复状态，请使用恢复删除。")
    # 规范证据生命周期：先检查，被引用禁止物理删除。
    document_ids = store.run_document_ids(run_id)
    if document_ids:
        norm_store = NormativeStore(store)
        referenced = [d for d in document_ids if norm_store.has_normative_references(d)]
        if referenced:
            return DeletionResult(
                False,
                "normative_referenced",
                "该批次包含已被规范版本/条款集/发布版引用的文档，禁止物理删除，只允许归档。",
            )
    vector_store = build_vector_store()
    try:
        vector_store.delete_segments_by_run(run_id)
    finally:
        vector_store.close()
    if not store.mark_vectors_deleted_sql_pending(run_id):
        return DeletionResult(False, "active", "无法记录向量删除状态，SQL 数据未删除。")
    if store.delete_run(run_id):
        return DeletionResult(True, "deleted", "实验批次及关联数据已删除。")
    return DeletionResult(
        False,
        "vectors_deleted_sql_pending",
        "向量已删除，但 SQL 数据仍保留；请使用恢复删除。",
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_lifecycle_protection.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/dashboard.py kg_extract_build/persistence.py kg_extract_build/tests/test_lifecycle_protection.py
git commit -m "feat: 规范证据生命周期删除保护"
```

---

### Task 13: Gold 固件与端到端冒烟

**Files:**
- Create: `kg_extract_build/tests/fixtures/spec_clause_gold.md`
- Create: `kg_extract_build/tests/test_normative_gold.py`
- Create: `kg_extract_build/scripts/normative_smoke.py`（可选；若目录不存在则新建 `scripts/`；tests 目录保持无 `__init__.py`，兄弟测试模块直接 `from test_x import Y`）

**Interfaces:**
- Consumes: Task 1-12 全部模块。
- Produces: 端到端冒烟脚本 `python -m kg_extract_build.scripts.normative_smoke`，在真实 Milvus + MiniLM 模型就位时跑通 登记→落库→编码→索引→发布→检索。

- [ ] **Step 1: 写失败测试**

`kg_extract_build/tests/fixtures/spec_clause_gold.md`：
```markdown
# 有限空间作业安全规程

## 第二章 作业要求

第二十条 作业前应通风，检测合格后方可进入。
进入前应确认作业票审批记录齐全。

第二十一条 作业期间应安排专人在外监护。

5.1.2 气体检测应使用经校准的检测仪器，并记录检测结果。

| 项目 | 要求 |
| --- | --- |
| 通风时间 | 作业前不低于30分钟 |
```

`kg_extract_build/tests/test_normative_gold.py`：
```python
import unittest
from pathlib import Path

from kg_extract_build.normative import parse_normative_clauses
from kg_extract_build.normative_segmentation import segment_clause


class GoldClauseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = Path(__file__).with_name("fixtures") / "spec_clause_gold.md"
        cls.text = fixture.read_text(encoding="utf-8")

    def test_gold_parses_law_and_numbered_clauses(self):
        clauses = parse_normative_clauses(self.text)
        numbers = [c.clause_number for c in clauses]
        self.assertEqual(numbers, ["第二十条", "第二十一条", "5.1.2"])

    def test_multi_paragraph_merges_into_one_clause(self):
        clauses = parse_normative_clauses(self.text)
        c20 = next(c for c in clauses if c.clause_number == "第二十条")
        self.assertIn("作业票审批记录", c20.raw_text)

    def test_markdown_table_stays_in_clause(self):
        clauses = parse_normative_clauses(self.text)
        self.assertIn("通风时间", self.text)

    def test_fallback_for_unstructured_section(self):
        clauses = parse_normative_clauses("附录\n\n应保存记录。\n\n不得违章作业。")
        self.assertTrue(all(c.clause_number is None for c in clauses))
        self.assertTrue(all(c.parse_status == "fallback" for c in clauses))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_gold.py -v`
Expected: FAIL（fixture 不存在）

- [ ] **Step 3: 实现**

按上面文件内容创建 fixture 与测试；再创建 `kg_extract_build/scripts/normative_smoke.py`：
```python
"""端到端冒烟：规范文档登记→索引→检索。前提：Milvus 服务运行、MiniLM 模型就位。"""

import os

from kg_extract_build import settings
from kg_extract_build.normative_encoder import (
    EncoderProfile, NormativeEncoder, build_encoder_profile_hash, model_revision,
)
from kg_extract_build.normative_indexer import NormativeIndexer
from kg_extract_build.normative_persistence import NormativeStore
from kg_extract_build.normative_registry import register_version
from kg_extract_build.normative_search import NormativeSearcher, SearchRequest
from kg_extract_build.normative_vector_store import build_normative_vector_store
from kg_extract_build.persistence import MySQLExperimentStore

SMOKE_TEXT = (
    "# 有限空间作业安全规程\n\n第二十条 作业前应通风。\n\n5.1.2 应记录检测结果。\n"
)


def main() -> None:
    if not settings.NORM_MILVUS_ENABLED:
        raise SystemExit("请先设置 KG_NORM_MILVUS_ENABLED=1 并启动 Milvus 服务。")
    store = NormativeStore(MySQLExperimentStore.from_env())
    store.initialize_schema()
    result = register_version(
        store, document_id=1, file_name="有限空间作业安全规程.md",
        content=SMOKE_TEXT, display_name="有限空间作业安全规程 2020",
        effective_year=2020, status="effective",
    )
    profile = EncoderProfile(
        embedding_model_key="paraphrase-multilingual-MiniLM-L12-v2",
        embedding_model_revision=model_revision(settings.NORM_VECTOR_MODEL_PATH),
        embedding_dimension=384, max_input_tokens=128,
    )
    encoder = NormativeEncoder(settings.NORM_VECTOR_MODEL_PATH, profile)
    vector_store = build_normative_vector_store()
    indexer = NormativeIndexer(store, vector_store, encoder, profile)
    build = indexer.build_index(result["version_id"])
    print("build_index:", build)
    if build["status"] != "ready":
        raise SystemExit(f"索引构建失败：{build}")
    release_id = indexer.build_release("smoke-release", [build["index_id"]])
    searcher = NormativeSearcher(store, vector_store, encoder, profile)
    outcome = searcher.search(SearchRequest("通风", 2025, release_id, {"scope_type": "all"}, top_k=5))
    print("evidence count:", len(outcome["evidence"]))
    for item in outcome["evidence"]:
        print(item["clause_number"], item["text"][:40])
    encoder.close()
    vector_store.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests/test_normative_gold.py -v`
Expected: PASS

（可选端到端，需环境就位）Run: `"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m kg_extract_build.scripts.normative_smoke`
Expected: `build_index: {'status': 'ready', ...}`，`evidence count: 1`，输出 `第二十条 有限空间作业安全规程...作业前应通风。`

- [ ] **Step 5: 提交**

```bash
git add kg_extract_build/tests/fixtures/spec_clause_gold.md kg_extract_build/tests/test_normative_gold.py kg_extract_build/scripts/normative_smoke.py
git commit -m "test: 规范条款 gold 固件与端到端冒烟脚本"
```

---

## 收尾

- [ ] 全量回归：`"D:/ProgramData/anaconda3/envs/env_agent/python.exe" -m pytest kg_extract_build/tests -q`，预期 57 + 新增（约 40+）全部通过。
- [ ] 更新 `README.md` 或 `CONTEXT.md`：记录 `KG_NORM_*` 配置与"规范向量索引"页面入口。
- [ ] 提交收尾。
