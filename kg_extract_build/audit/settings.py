"""审核模块专用配置。"""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def audit_env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value or default).expanduser().resolve()


AUDIT_STORAGE_DIR = audit_env_path(
    "KG_AUDIT_STORAGE_DIR", PROJECT_ROOT / "audit_data"
)
AUDIT_TASK_LIBRARY_PATH = audit_env_path(
    "KG_AUDIT_TASK_LIBRARY_PATH",
    PROJECT_ROOT / "docs" / "audit-task-library" / "v1" / "audit-task-library.v1.1.0.json",
)
AUDIT_RISK_CATALOG_PATH = audit_env_path(
    "KG_AUDIT_RISK_CATALOG_PATH",
    PROJECT_ROOT / "kg_extract_build" / "audit" / "resources" / "risk_catalog",
)
AUDIT_MAX_FILE_MB = int(os.getenv("KG_AUDIT_MAX_FILE_MB", "50"))
AUDIT_DOC_CONVERTER = os.getenv("KG_AUDIT_DOC_CONVERTER", "auto").strip().lower()
LIBREOFFICE_PATH = audit_env_path(
    "KG_LIBREOFFICE_PATH",
    Path(r"D:\Program Files (x86)\LibreOffice\program\soffice.exe"),
)
AUDIT_CONVERSION_TIMEOUT = int(os.getenv("KG_AUDIT_CONVERSION_TIMEOUT", "120"))
