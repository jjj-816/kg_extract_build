import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscoveredDocument:
    name: str
    extension: str
    size_bytes: int


def discover_documents(folder_path):
    """Scan *direct* children of *folder_path* for .md / .txt files.

    Raises ``ValueError`` when the folder does not exist or is not a
    directory.  The caller is responsible for passing a valid path; this
    function will never create a missing folder.
    """
    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists():
        raise ValueError(f"文档文件夹不存在：{folder}")
    if not folder.is_dir():
        raise ValueError(f"文档路径不是文件夹：{folder}")
    items = []
    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
            items.append(
                DiscoveredDocument(
                    name=path.name,
                    extension=path.suffix.lower(),
                    size_bytes=path.stat().st_size,
                )
            )
    return sorted(items, key=lambda item: item.name.lower())


class BreakpointManager:
    def __init__(self, record_path):
        self.record_path = record_path
        self.processed = self._load_record()

    def _load_record(self):
        if self.record_path.exists():
            with self.record_path.open("r", encoding="utf-8") as f:
                return set(json.load(f))
        return set()

    def is_processed(self, file_name):
        return file_name in self.processed

    def mark_processed(self, file_name):
        self.processed.add(file_name)
        with self.record_path.open("w", encoding="utf-8") as f:
            json.dump(sorted(self.processed), f, ensure_ascii=False, indent=2)


class DocumentLoader:
    def __init__(
        self,
        folder_path,
        breakpoint_manager,
        respect_breakpoint=True,
        selected_files=None,
    ):
        self.folder_path = Path(folder_path).expanduser().resolve()
        self.breakpoint_manager = breakpoint_manager
        self.respect_breakpoint = respect_breakpoint
        self.selected_files = None if selected_files is None else set(selected_files)
        if not self.folder_path.is_dir():
            raise ValueError(f"文档文件夹无效：{self.folder_path}")
        if self.selected_files is not None:
            for name in self.selected_files:
                if Path(name).name != name:
                    raise ValueError(f"只能选择当前目录中的文件名：{name}")
                target = self.folder_path / name
                if not target.is_file():
                    raise ValueError(f"选定文件不存在或无法访问：{name}")
                resolved = target.resolve()
                try:
                    resolved.relative_to(self.folder_path)
                except ValueError as exc:
                    raise ValueError(
                        f"选定文件不在文档文件夹内：{name}"
                    ) from exc

    def load_all_unprocessed_docs(self):
        docs = {}
        for file_name in os.listdir(self.folder_path):
            if Path(file_name).suffix.lower() not in {".txt", ".md"}:
                continue
            if self.selected_files is not None and file_name not in self.selected_files:
                continue
            if (
                self.respect_breakpoint
                and self.breakpoint_manager.is_processed(file_name)
            ):
                continue
            path = self.folder_path / file_name
            try:
                docs[file_name] = path.read_text(encoding="utf-8")
                print(f"待处理文档：{file_name}")
            except Exception as exc:
                raise OSError(
                    f"读取文档失败 {file_name}：{exc}"
                ) from exc
        return docs
