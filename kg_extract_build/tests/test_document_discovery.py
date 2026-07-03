import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kg_extract_build.documents import (
    BreakpointManager,
    DocumentLoader,
    discover_documents,
)


class DocumentDiscoveryTests(unittest.TestCase):
    def test_discovers_only_direct_markdown_and_text_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.txt").write_text("乙", encoding="utf-8")
            (root / "a.md").write_text("甲", encoding="utf-8")
            (root / "skip.pdf").write_bytes(b"pdf")
            (root / "nested").mkdir()
            (root / "nested" / "c.md").write_text("丙", encoding="utf-8")

            files = discover_documents(root)

            self.assertEqual([item.name for item in files], ["a.md", "b.txt"])
            self.assertEqual(files[0].size_bytes, len("甲".encode("utf-8")))

    def test_missing_folder_is_rejected_without_being_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            with self.assertRaisesRegex(ValueError, "不存在"):
                discover_documents(missing)
            self.assertFalse(missing.exists())

    def test_loader_reads_only_selected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("甲", encoding="utf-8")
            (root / "b.md").write_text("乙", encoding="utf-8")
            manager = BreakpointManager(root / "processed.json")
            loader = DocumentLoader(
                root,
                manager,
                respect_breakpoint=False,
                selected_files=("b.md",),
            )

            self.assertEqual(loader.load_all_unprocessed_docs(), {"b.md": "乙"})

    def test_loader_reads_uppercase_supported_extension_found_by_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "UPPER.MD").write_text("内容", encoding="utf-8")
            manager = BreakpointManager(root / "processed.json")

            discovered = discover_documents(root)
            loader = DocumentLoader(
                root,
                manager,
                respect_breakpoint=False,
                selected_files=tuple(item.name for item in discovered),
            )

            self.assertEqual(
                loader.load_all_unprocessed_docs(),
                {"UPPER.MD": "内容"},
            )

    def test_loader_raises_when_selected_document_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("内容", encoding="utf-8")
            manager = BreakpointManager(root / "processed.json")
            loader = DocumentLoader(
                root,
                manager,
                respect_breakpoint=False,
                selected_files=("a.md",),
            )

            with patch.object(
                Path,
                "read_text",
                side_effect=UnicodeDecodeError(
                    "utf-8", b"\xff", 0, 1, "invalid start byte"
                ),
            ):
                with self.assertRaisesRegex(OSError, "读取文档失败.*a.md"):
                    loader.load_all_unprocessed_docs()

    def test_loader_rejects_path_like_selected_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = BreakpointManager(root / "processed.json")
            with self.assertRaisesRegex(ValueError, "文件名"):
                DocumentLoader(root, manager, selected_files=("../outside.md",))


    def test_loader_rejects_nonexistent_selected_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("甲", encoding="utf-8")
            manager = BreakpointManager(root / "processed.json")
            with self.assertRaisesRegex(ValueError, "不存在"):
                DocumentLoader(
                    root, manager, selected_files=("missing.md",)
                )

    def test_loader_rejects_file_resolving_to_prefix_collision_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "docs")
            outside = Path(tmp, "docs-escape")
            root.mkdir()
            outside.mkdir()
            (root / "a.md").write_text("inside", encoding="utf-8")
            escaped = (outside / "a.md").resolve()
            real_resolve = Path.resolve

            def fake_resolve(path, *args, **kwargs):
                if path.parent == root and path.name == "a.md":
                    return escaped
                return real_resolve(path, *args, **kwargs)

            manager = BreakpointManager(root / "processed.json")
            with patch.object(Path, "resolve", fake_resolve):
                with self.assertRaisesRegex(ValueError, "不在文档文件夹内"):
                    DocumentLoader(
                        root, manager, selected_files=("a.md",)
                    )


if __name__ == "__main__":
    unittest.main()
