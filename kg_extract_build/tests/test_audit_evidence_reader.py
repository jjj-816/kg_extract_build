import tempfile
import unittest
from pathlib import Path

from docx import Document

from kg_extract_build.audit.evidence_reader import build_task_evidence_export, safe_export_filename
from kg_extract_build.audit.preview import create_audit_preview


class EvidenceReaderTests(unittest.TestCase):
    def test_exports_all_tasks_as_readable_csv_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "方案.docx"
            document = Document()
            document.add_paragraph("第一章 编制依据")
            document.add_paragraph("1.1 文件依据")
            document.add_paragraph("《测试规范》")
            document.add_paragraph("第四章 施工安排")
            document.add_paragraph("4.1 施工顺序")
            document.add_paragraph("作业准备→开工条件确认→施工")
            document.save(path)
            preview = create_audit_preview("方案.docx", path.read_bytes(), storage_dir=directory)
            exported = build_task_evidence_export(preview)
            self.assertEqual(len(exported), 42)
            self.assertEqual(exported.columns.tolist()[-2:], ["人工判断", "备注"])
            self.assertTrue(exported["任务 ID"].iloc[0])

    def test_export_filename_removes_windows_illegal_characters(self):
        self.assertEqual(safe_export_filename('方案:测试.docx'), '方案_测试_任务证据.csv')
