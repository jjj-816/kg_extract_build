import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document

from kg_extract_build.audit.word_converter import WordConversionCapability, convert_doc_to_docx


class AuditWordConverterTests(unittest.TestCase):
    def test_auto_mode_falls_back_to_libreoffice_after_word_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "方案.doc"
            source.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"test")

            def write_docx(_source, output_dir, _timeout):
                output = Path(output_dir) / "方案.docx"
                document = Document()
                document.add_paragraph("转换后的施工方案")
                document.save(output)
                return "7.6", {"attempted": True, "fallback": True}

            with patch(
                "kg_extract_build.audit.word_converter.doc_conversion_capability",
                return_value=WordConversionCapability(True, "test", True, True),
            ), patch(
                "kg_extract_build.audit.word_converter._word_com_convert",
                side_effect=RuntimeError("Word 此命令无效"),
            ), patch(
                "kg_extract_build.audit.word_converter._libreoffice_convert",
                side_effect=write_docx,
            ):
                result = convert_doc_to_docx(source, root / "converted", mode="auto")

            self.assertEqual(result.converter_name, "libreoffice")
            self.assertTrue(result.path.is_file())
            self.assertIn("word_error", result.diagnostics)
            self.assertTrue(result.content_hash)


if __name__ == "__main__":
    unittest.main()
