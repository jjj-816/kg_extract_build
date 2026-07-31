"""审核数据域的显式初始化、健康检查与阶段 1 持久化。"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .bindings import build_task_bindings
from .models import ParsedAuditDocument
from .task_library import PublishedTaskLibrary


AUDIT_TABLES = (
    "audit_document", "audit_document_block", "audit_run", "audit_run_work_type",
    "audit_task_execution", "audit_declared_norm", "audit_task_evidence",
    "audit_retrieval_candidate", "audit_applicability_result", "audit_llm_call",
    "audit_issue", "audit_human_review", "audit_report",
)
AUDIT_REQUIRED_COLUMNS = {
    "audit_document": {"document_id", "converted_hash", "converter_name", "converter_version", "conversion_status", "conversion_diagnostics", "image_manifest_json"},
    "audit_run": {"run_id", "context_confirmed_by", "context_confirmed_at", "config_snapshot"},
    "audit_task_execution": {"run_id", "task_id", "task_snapshot", "execution_status"},
}


def audit_schema_path() -> Path:
    return Path(__file__).with_name("schema.sql")


def initialize_audit_schema(connection) -> None:
    """仅供 ``python -m kg_extract_build.init_storage`` 显式调用。"""
    sql_text = audit_schema_path().read_text(encoding="utf-8")
    with connection.cursor() as cursor:
        for statement in sql_text.split(";"):
            if statement.strip():
                cursor.execute(statement.strip())
    connection.commit()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def format_beijing_time(value: datetime | None) -> str | None:
    """数据库 DATETIME 按 UTC 解释，页面统一显示北京时间。"""
    if value is None:
        return None
    utc_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return utc_value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S UTC+08:00（北京时间）")


def format_utc_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    utc_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_audit_context(context: dict, reviewer_name: str) -> None:
    required = {
        "项目或平台名称": context.get("project_name"),
        "审核基准年份": context.get("audit_year"),
        "作业目的": context.get("work_purpose"),
        "涉及作业类型": context.get("work_types"),
        "审核确认人": reviewer_name,
    }
    missing = [name for name, value in required.items() if not value or (isinstance(value, str) and not value.strip())]
    if missing:
        raise ValueError("创建审核运行前必须填写：" + "、".join(missing))
    if not isinstance(context["audit_year"], int) or not 2000 <= context["audit_year"] <= 2100:
        raise ValueError("审核基准年份无效")


class MySQLAuditStore:
    def __init__(self, **connection_options):
        self.connection_options = connection_options
        self._connection_instance = None

    @classmethod
    def from_env(cls):
        return cls(
            host=os.getenv("KG_MYSQL_HOST", "127.0.0.1"), port=int(os.getenv("KG_MYSQL_PORT", "3306")),
            user=os.getenv("KG_MYSQL_USER", "root"), password=os.getenv("KG_MYSQL_PASSWORD", ""),
            database=os.getenv("KG_MYSQL_DATABASE", "kg_experiments"), charset=os.getenv("KG_MYSQL_CHARSET", "utf8mb4"),
            autocommit=False,
        )

    def _connection(self):
        if self._connection_instance is None:
            import pymysql
            self._connection_instance = pymysql.connect(**self.connection_options)
        else:
            self._connection_instance.ping(reconnect=True)
        return self._connection_instance

    def initialize_schema(self) -> None:
        initialize_audit_schema(self._connection())

    def schema_health(self) -> tuple[bool, str]:
        """只查询 information_schema，绝不在页面请求中执行 DDL。"""
        connection = self._connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_name IN (" +
                ",".join(["%s"] * len(AUDIT_TABLES)) + ")",
                (self.connection_options["database"], *AUDIT_TABLES),
            )
            existing = {row[0] for row in cursor.fetchall()}
        missing = [name for name in AUDIT_TABLES if name not in existing]
        if missing:
            return False, "审核数据表尚未初始化（缺少：" + "、".join(missing) + "）。请在确认环境后手动执行 python -m kg_extract_build.init_storage。"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=%s AND table_name IN (" +
                ",".join(["%s"] * len(AUDIT_REQUIRED_COLUMNS)) + ")",
                (self.connection_options["database"], *AUDIT_REQUIRED_COLUMNS),
            )
            columns: dict[str, set[str]] = {}
            for table_name, column_name in cursor.fetchall():
                columns.setdefault(table_name, set()).add(column_name)
        incompatible = [f"{table} 缺少 {','.join(sorted(required - columns.get(table, set())))}" for table, required in AUDIT_REQUIRED_COLUMNS.items() if required - columns.get(table, set())]
        if incompatible:
            return False, "审核表结构与当前代码不兼容：" + "；".join(incompatible) + "。请执行受控迁移后再创建审核运行。"
        return True, "审核数据表健康（13 张表）"

    def _save_parsed_document(self, cursor, parsed: ParsedAuditDocument, now) -> None:
        document = parsed.document
        image_manifest = [
            {**asdict(image), "stored_path": str(image.stored_path)} for image in parsed.images
        ]
        cursor.execute(
                    """INSERT INTO audit_document
                    (document_id, original_filename, file_type, content_hash, original_path, converted_path,
                     converted_hash, converter_name, converter_version, conversion_status, conversion_diagnostics,
                     image_manifest_json, parse_status, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE document_id=VALUES(document_id)""",
                    (document.document_id, document.original_filename, document.file_type, document.content_hash,
                     str(document.original_path), str(document.converted_path) if document.converted_path else None,
                     document.converted_hash, document.converter_name, document.converter_version, document.conversion_status,
                     _json(document.conversion_diagnostics), _json(image_manifest), "parsed", now),
        )
        rows = [(
                    block.block_id, block.document_id, block.ordinal, block.block_type, _json(block.section_path),
                    block.source_locator, block.raw_text, block.normalized_text,
                    _json(block.table_json) if block.table_json else None, _json(block.image_refs), block.parse_status, now,
        ) for block in parsed.blocks]
        if rows:
            cursor.executemany(
                        """INSERT INTO audit_document_block
                        (block_id,document_id,ordinal,block_type,section_path,source_locator,raw_text,normalized_text,
                         table_json,image_refs_json,parse_status,created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE block_id=VALUES(block_id)""", rows)

    def save_parsed_document(self, parsed: ParsedAuditDocument) -> None:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                self._save_parsed_document(cursor, parsed, datetime.now(timezone.utc).replace(tzinfo=None))
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def create_confirmed_run(self, parsed: ParsedAuditDocument, library: PublishedTaskLibrary, context: dict, reviewer_name: str) -> str:
        """在人工确认上下文后创建不可变运行快照及全部 42 项待执行任务。"""
        connection, now = self._connection(), datetime.now(timezone.utc).replace(tzinfo=None)
        run_id = str(uuid.uuid4())
        bindings = build_task_bindings(library)
        validate_audit_context(context, reviewer_name)
        try:
            with connection.cursor() as cursor:
                self._save_parsed_document(cursor, parsed, now)
                cursor.execute(
                    """INSERT INTO audit_run
                    (run_id,document_id,status,project_name,audit_year,work_purpose,task_library_id,task_library_version,
                     task_library_hash,binding_version,config_snapshot,context_confirmed_by,context_confirmed_at,created_at,updated_at)
                    VALUES (%s,%s,'context_confirmed',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, parsed.document.document_id, context.get("project_name") or None, context.get("audit_year"),
                     context.get("work_purpose") or None, library.task_library_id, library.version, library.sha256,
                     "stage1-v1", _json(context), reviewer_name, now, now, now),
                )
                work_types = [(run_id, value) for value in context.get("work_types", [])]
                if work_types:
                    cursor.executemany("INSERT INTO audit_run_work_type (run_id,work_type) VALUES (%s,%s)", work_types)
                executions = []
                for task in library.tasks:
                    snapshot = asdict(task)
                    snapshot["binding"] = asdict(bindings[task.task_id])
                    executions.append((run_id, task.task_id, _json(snapshot), task.route, "pending", now, now))
                cursor.executemany(
                    """INSERT INTO audit_task_execution
                    (run_id,task_id,task_snapshot,route,execution_status,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""", executions)
            connection.commit()
            return run_id
        except Exception:
            connection.rollback()
            raise

    def load_run(self, run_id: str) -> dict | None:
        with self._connection().cursor() as cursor:
            cursor.execute(
                """SELECT r.run_id, r.document_id, d.original_filename, r.status, r.project_name, r.audit_year,
                          r.work_purpose, r.task_library_version, r.config_snapshot, r.context_confirmed_by,
                          r.context_confirmed_at, r.created_at
                   FROM audit_run r JOIN audit_document d ON d.document_id=r.document_id WHERE r.run_id=%s""", (run_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute("SELECT COUNT(*) FROM audit_task_execution WHERE run_id=%s", (run_id,))
            task_count = cursor.fetchone()[0]
        return {
            "run_id": row[0], "document_id": row[1], "document_name": row[2], "status": row[3],
            "project_name": row[4], "audit_year": row[5], "work_purpose": row[6], "task_library_version": row[7],
            "config": json.loads(row[8]), "reviewer_name": row[9],
            "confirmed_at_utc": format_utc_time(row[10]), "confirmed_at_beijing": format_beijing_time(row[10]),
            "created_at_utc": format_utc_time(row[11]), "created_at_beijing": format_beijing_time(row[11]),
            "task_count": task_count,
        }

    def close(self) -> None:
        if self._connection_instance is not None:
            self._connection_instance.close()
            self._connection_instance = None
