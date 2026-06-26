import json
import os


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
    def __init__(self, folder_path, breakpoint_manager):
        self.folder_path = folder_path
        self.breakpoint_manager = breakpoint_manager
        self.folder_path.mkdir(parents=True, exist_ok=True)

    def load_all_unprocessed_docs(self):
        docs = {}
        for file_name in os.listdir(self.folder_path):
            if not file_name.endswith((".txt", ".md")):
                continue
            if self.breakpoint_manager.is_processed(file_name):
                continue
            path = self.folder_path / file_name
            try:
                docs[file_name] = path.read_text(encoding="utf-8")
                print(f"待处理文档：{file_name}")
            except Exception as exc:
                print(f"读取失败 {file_name}：{exc}")
        return docs

