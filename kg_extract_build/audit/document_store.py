"""审核源 Word 的受控保存与文件身份管理。"""

from __future__ import annotations

import hashlib
import re
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from .models import StoredAuditDocument
from .settings import AUDIT_MAX_FILE_MB, AUDIT_STORAGE_DIR


SUPPORTED_WORD_EXTENSIONS = {".docx", ".doc"}
_OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")


class AuditDocumentError(ValueError):
    """上传文件不能作为审核源 Word 使用。"""


def safe_filename(filename: str) -> str:
    name = Path(filename or "施工方案").name.strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:180] or "施工方案"


def _validate_file_content(extension: str, content: bytes) -> None:
    if extension == ".docx" and not zipfile.is_zipfile(BytesIO(content)):
        raise AuditDocumentError("上传文件扩展名为 .docx，但内容不是有效的 Office 压缩包")
    if extension == ".doc" and not content.startswith(_OLE_SIGNATURE):
        raise AuditDocumentError("上传文件扩展名为 .doc，但内容不是有效的 Word 二进制文档")


def store_uploaded_word(
    filename: str,
    content: bytes,
    storage_dir: str | Path | None = None,
    max_file_mb: int | None = None,
) -> StoredAuditDocument:
    safe_name = safe_filename(filename)
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED_WORD_EXTENSIONS:
        raise AuditDocumentError("施工方案仅支持 .docx 或 .doc 格式")
    if not content:
        raise AuditDocumentError("上传文件为空")
    limit_bytes = int(max_file_mb or AUDIT_MAX_FILE_MB) * 1024 * 1024
    if len(content) > limit_bytes:
        raise AuditDocumentError(f"上传文件超过 {limit_bytes // 1024 // 1024} MB 限制")
    _validate_file_content(extension, content)
    document_id = str(uuid.uuid4())
    root = Path(storage_dir or AUDIT_STORAGE_DIR).expanduser().resolve()
    original_dir = root / "documents" / document_id / "original"
    original_dir.mkdir(parents=True, exist_ok=False)
    path = original_dir / safe_name
    path.write_bytes(content)
    return StoredAuditDocument(
        document_id=document_id,
        original_filename=filename,
        file_type=extension.lstrip("."),
        content_hash=hashlib.sha256(content).hexdigest().upper(),
        original_path=path,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
