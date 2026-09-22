"""代表性运维来源格式的安全解析行为测试。"""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from netops_copilot.infrastructure.ingestion.parsers import (
    ParseErrorCode,
    ParseLimits,
    ParseValidationError,
    parse_path,
)


class IngestionParserTests(unittest.TestCase):
    def _write(self, directory: Path, name: str, content: str) -> Path:
        path = directory / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_markdown_json_jsonl_yaml_and_configuration_have_locations_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markdown = self._write(root, "sop.md", "---\nsource_id: sop-1\nsite_id: site-gz-dc\n---\n\n# OSPF\n")
            json_path = self._write(root, "tickets.json", '[{"source_id":"ticket-1","text":"OSPF ExStart"}]')
            jsonl = self._write(root, "alarms.jsonl", '{"source_id":"alarm-1","content":"peer down"}\n')
            yaml_path = self._write(root, "topology.yaml", "source_id: topo-1\ncontent: spine leaf\n")
            config = self._write(root, "device.cfg", "interface GigabitEthernet0/0\n description uplink\n")

            records = [parse_path(path)[0] for path in (markdown, json_path, jsonl, yaml_path, config)]
            self.assertEqual(
                [record.source_id for record in records],
                ["sop-1", "ticket-1", "alarm-1", "topo-1", "device"],
            )
            self.assertTrue(all(record.content_hash for record in records))
            self.assertTrue(all(record.location.locator for record in records))

    def test_malformed_and_unsupported_sources_are_rejected_without_content_in_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malformed = self._write(root, "bad.jsonl", '{"broken":\n')
            unsupported = self._write(root, "payload.bin", "secret=not-logged")
            for path, code in ((malformed, ParseErrorCode.MALFORMED), (unsupported, ParseErrorCode.UNSUPPORTED)):
                with self.assertRaises(ParseValidationError) as context:
                    parse_path(path)
                self.assertEqual(context.exception.code, code)
                self.assertNotIn("not-logged", str(context.exception))

    def test_pdf_encryption_scan_and_limits_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            encrypted = root / "encrypted.pdf"
            encrypted.write_bytes(b"%PDF-1.7 /Encrypt")
            scanned = root / "scanned.pdf"
            scanned.write_bytes(b"%PDF-1.7 /Type /Page")
            long_text = self._write(root, "long.txt", "a\n" * 10)
            for path, code in ((encrypted, ParseErrorCode.ENCRYPTED), (scanned, ParseErrorCode.SCANNED)):
                with self.assertRaises(ParseValidationError) as context:
                    parse_path(path)
                self.assertEqual(context.exception.code, code)
            with self.assertRaisesRegex(ParseValidationError, "line limit"):
                parse_path(long_text, ParseLimits(max_lines=2))

    def test_digital_native_pdf_docx_and_xlsx_keep_structural_locations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "native.pdf"
            pdf.write_bytes(b"%PDF-1.7 /Type /Page (OSPF ExStart)")
            docx = root / "manual.docx"
            with zipfile.ZipFile(docx, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<document xmlns="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><body><p><r><t>OSPF ExStart</t></r></p></body></document>',
                )
            xlsx = root / "facts.xlsx"
            with zipfile.ZipFile(xlsx, "w") as archive:
                archive.writestr(
                    "xl/workbook.xml",
                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Facts" sheetId="1"/></sheets></workbook>',
                )
                archive.writestr(
                    "xl/worksheets/sheet1.xml",
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>OSPF</t></is></c></row></sheetData></worksheet>',
                )

            self.assertEqual(parse_path(pdf)[0].location.locator, "page:1")
            self.assertEqual(parse_path(docx)[0].location.locator, "paragraph:1")
            self.assertIn("sheet:Facts!A1", parse_path(xlsx)[0].location.locator)
