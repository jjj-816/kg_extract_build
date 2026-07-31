"""审核数据域的最小 MySQL 初始化和文档证据持久化。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .models import AuditDocumentBlock, ParsedAuditDocument


def audit_schema_path() -> Path:
    return Path(__file__).with_name("schema.sql")


def initialize_audit_schema(connection) -> None:
    sql_text = audit_schema_path().read_text(encoding="utf-8")
    with connection.cursor() as cursor:
        for statement in sql_text.split(";"):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)
    connection.commit()


class MySQLAuditStore:
    def __init__(self, **connection_options):
        self.connection_options = connection_options
        self._connection_instance = None

    @classmethod
    def from_env(cls):
        return cls(
            host=os.getenv("KG_MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("KG_MYSQL_PORT", "3306")),
            user=os.getenv("KG_MYSQL_USER", "root"),
            password=os.getenv("KG_MYSQL_PASSWORD", ""),
            database=os.getenv("KG_MYSQL_DATABASE", "kg_experiments"),
            charset=os.getenv("KG_MYSQL_CHARSET", "utf8mb4"),
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

    def save_parsed_document(self, parsed: ParsedAuditDocument) -> None:
        connection = self._connection()
        document = parsed.document
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO audit_document
                    (document_id, original_filename, file_type, content_hash, original_path,
                     converted_path, parse_status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        document.document_id, document.original_filename, document.file_type,
                        document.content_hash, str(document.original_path),
                        str(document.converted_path) if document.converted_path else None,
                        "parsed", now,
                    ),
                )
                rows = []
                for block in parsed.blocks:
                    rows.append((
                        block.block_id, block.document_id, block.ordinal, block.block_type,
                        json.dumps(block.section_path, ensure_ascii=False), block.source_locator,
                        block.raw_text, block.normalized_text,
                        json.dumps(block.table_json, ensure_ascii=False) if block.table_json else None,
                        json.dumps(block.image_refs, ensure_ascii=False), block.parse_status, now,
                    ))
                if rows:
                    cursor.executemany(
                        """
                        INSERT INTO audit_document_block
                        (block_id, document_id, ordinal, block_type, section_path, source_locator,
                         raw_text, normalized_text, table_json, image_refs_json, parse_status, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        rows,
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def close(self) -> None:
        if self._connection_instance is not None:
            self._connection_instance.close()
            self._connection_instance = None
