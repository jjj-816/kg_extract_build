"""将传统 .doc 转换为只读解析使用的 .docx 副本。"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WordConversionCapability:
    available: bool
    message: str


def doc_conversion_capability() -> WordConversionCapability:
    if platform.system() != "Windows":
        return WordConversionCapability(False, "当前系统仅支持通过 Windows Word COM 转换 .doc")
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
    except ImportError:
        return WordConversionCapability(False, "缺少 pywin32，无法转换 .doc")
    return WordConversionCapability(True, "可尝试通过本机 Microsoft Word 转换 .doc")


def convert_doc_to_docx(source_path: str | Path, output_dir: str | Path) -> Path:
    source = Path(source_path).expanduser().resolve()
    destination_dir = Path(output_dir).expanduser().resolve()
    if source.suffix.lower() != ".doc":
        raise ValueError("仅支持将 .doc 转换为 .docx")
    if not source.is_file():
        raise FileNotFoundError(f".doc 文件不存在：{source}")
    capability = doc_conversion_capability()
    if not capability.available:
        raise RuntimeError(capability.message)
    destination_dir.mkdir(parents=True, exist_ok=True)
    output_path = destination_dir / f"{source.stem}.docx"
    import pythoncom
    import win32com.client

    word = None
    document = None
    pythoncom.CoInitialize()
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(str(source))
        document.SaveAs2(str(output_path), FileFormat=16)
    finally:
        if document is not None:
            document.Close(False)
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()
    if not output_path.is_file():
        raise RuntimeError("Word 未生成可解析的 .docx 文件")
    return output_path
