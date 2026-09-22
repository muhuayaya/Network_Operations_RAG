"""支持的运维来源格式的安全确定性解析器。"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml


class ParseErrorCode(StrEnum):
    """可安全暴露到日志和 API 的显式解析校验结果。"""

    MALFORMED = "malformed"
    UNSUPPORTED = "unsupported"
    ENCRYPTED = "encrypted"
    SCANNED = "scanned"
    UNSAFE = "unsafe"
    RESOURCE_LIMIT = "resource_limit"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"


class ParseValidationError(ValueError):
    """来源在进入索引或模型输入前被拒绝。"""

    def __init__(self, code: ParseErrorCode, path: Path, detail: str) -> None:
        self.code = code
        self.path = path.name
        self.detail = detail
        super().__init__(f"{code.value}: {path.name}: {detail}")


@dataclass(frozen=True, slots=True)
class ParseLimits:
    """文档提取前及提取期间应用的资源边界。"""

    max_bytes: int = 5_000_000
    max_lines: int = 20_000
    max_pdf_pages: int = 100
    max_sheets: int = 50
    max_cells: int = 20_000


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """为引用保留的稳定可读来源定位。"""

    path: str
    locator: str


@dataclass(frozen=True, slots=True)
class ParsedRecord:
    """与下游切分无关的规范化解析结果。"""

    source_id: str
    content: str
    metadata: Mapping[str, str]
    location: SourceLocation
    content_hash: str
    parser_version: str = "1"


SUPPORTED_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".cfg",
        ".conf",
        ".config",
        ".pdf",
        ".docx",
        ".xlsx",
    }
)


def parse_path(path: str | Path, limits: ParseLimits | None = None) -> tuple[ParsedRecord, ...]:
    """解析一个支持的来源路径，但不执行其中嵌入的内容。"""
    source_path = Path(path)
    limits = limits or ParseLimits()
    if source_path.is_symlink() or not source_path.is_file():
        raise ParseValidationError(ParseErrorCode.UNSAFE, source_path, "source must be a regular file")
    suffix = source_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ParseValidationError(ParseErrorCode.UNSUPPORTED, source_path, "file type is not supported")
    try:
        size = source_path.stat().st_size
    except OSError as error:
        raise ParseValidationError(ParseErrorCode.UNSAFE, source_path, "source cannot be inspected") from error
    if size > limits.max_bytes:
        raise ParseValidationError(ParseErrorCode.RESOURCE_LIMIT, source_path, "file exceeds byte limit")
    if suffix == ".pdf":
        return _parse_pdf(source_path, limits)
    if suffix in {".docx", ".xlsx"}:
        return _parse_office(source_path, limits)
    text = _read_text(source_path)
    if len(text.splitlines()) > limits.max_lines:
        raise ParseValidationError(ParseErrorCode.RESOURCE_LIMIT, source_path, "line limit exceeded")
    if suffix in {".md", ".markdown"}:
        return _parse_markdown(source_path, text)
    if suffix == ".txt" or suffix in {".cfg", ".conf", ".config"}:
        return (_text_record(source_path, text, {}, "text" if suffix == ".txt" else "configuration"),)
    if suffix == ".jsonl":
        return _parse_jsonl(source_path, text)
    return _parse_structured(source_path, text, suffix)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "source is not UTF-8 text") from error
    except OSError as error:
        raise ParseValidationError(ParseErrorCode.UNSAFE, path, "source cannot be read") from error


def _parse_markdown(path: Path, text: str) -> tuple[ParsedRecord, ...]:
    metadata, content = _front_matter(text, path)
    return (_text_record(path, content, metadata, metadata.get("source_type", "markdown")),)


def _parse_jsonl(path: Path, text: str) -> tuple[ParsedRecord, ...]:
    records: list[ParsedRecord] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ParseValidationError(ParseErrorCode.MALFORMED, path, f"invalid JSON at line {line_number}") from error
        records.append(_structured_record(path, value, f"jsonl:line:{line_number}"))
    if not records:
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "JSONL contains no records")
    return tuple(records)


def _parse_structured(path: Path, text: str, suffix: str) -> tuple[ParsedRecord, ...]:
    try:
        value = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "structured source cannot be parsed") from error
    if value is None:
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "structured source is empty")
    values = value if isinstance(value, list) else [value]
    if not all(isinstance(item, (Mapping, list, str, int, float, bool)) for item in values):
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "structured record has unsupported shape")
    return tuple(_structured_record(path, item, f"{suffix[1:]}:item:{index}") for index, item in enumerate(values))


def _front_matter(text: str, path: Path) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "unterminated YAML front matter")
    try:
        raw = yaml.safe_load(parts[0][3:].strip()) or {}
    except yaml.YAMLError as error:
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "invalid YAML front matter") from error
    if not isinstance(raw, Mapping):
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "front matter must be a mapping")
    metadata = {str(key): _stringify(value) for key, value in raw.items()}
    return metadata, parts[1].lstrip("\n")


def _structured_record(path: Path, value: Any, locator: str) -> ParsedRecord:
    metadata: dict[str, str] = {}
    if isinstance(value, Mapping):
        for key in (
            "source_id",
            "source_type",
            "vendor",
            "model",
            "os_family",
            "site_id",
            "device_id",
            "version",
            "effective_at",
            "security_level",
        ):
            if key in value and value[key] is not None:
                metadata[key] = _stringify(value[key])
        content_value = value.get("text", value.get("content", value))
    else:
        content_value = value
    content = content_value if isinstance(content_value, str) else json.dumps(value, sort_keys=True, default=_json_default)
    source_id = metadata.get("source_id", f"{path.stem}:{locator}")
    return _record(path, source_id, content, metadata, locator)


def _text_record(path: Path, content: str, metadata: Mapping[str, str], source_type: str) -> ParsedRecord:
    values = dict(metadata)
    values.setdefault("source_type", source_type)
    return _record(path, values.get("source_id", path.stem), content, values, "text")


def _record(path: Path, source_id: str, content: str, metadata: Mapping[str, str], locator: str) -> ParsedRecord:
    if not content.strip():
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "record contains no text")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return ParsedRecord(source_id, content, dict(metadata), SourceLocation(str(path), locator), digest)


def _parse_pdf(path: Path, limits: ParseLimits) -> tuple[ParsedRecord, ...]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "invalid PDF header")
    if b"/Encrypt" in data:
        raise ParseValidationError(ParseErrorCode.ENCRYPTED, path, "encrypted PDF is not accepted")
    page_count = len(re.findall(rb"/Type\s*/Page(?:\s|/|>)", data)) or 1
    if page_count > limits.max_pdf_pages:
        raise ParseValidationError(ParseErrorCode.RESOURCE_LIMIT, path, "PDF page limit exceeded")
    text_fragments = [fragment.decode("latin-1", errors="ignore") for fragment in re.findall(rb"\(([^()]*)\)", data)]
    text = " ".join(fragment.replace("\\n", "\n") for fragment in text_fragments).strip()
    if not text:
        raise ParseValidationError(ParseErrorCode.SCANNED, path, "PDF contains no selectable text")
    return (_record(path, path.stem, text, {"source_type": "pdf"}, "page:1"),)


def _parse_office(path: Path, limits: ParseLimits) -> tuple[ParsedRecord, ...]:
    try:
        with zipfile.ZipFile(path) as archive:
            _check_zip_safety(path, archive)
            if path.suffix.lower() == ".docx":
                return _parse_docx(path, archive)
            return _parse_xlsx(path, archive, limits)
    except zipfile.BadZipFile as error:
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "Office package is damaged") from error


def _check_zip_safety(path: Path, archive: zipfile.ZipFile) -> None:
    for info in archive.infolist():
        name = info.filename.lower()
        if info.flag_bits & 0x1:
            raise ParseValidationError(ParseErrorCode.ENCRYPTED, path, "encrypted Office package is not accepted")
        if any(token in name for token in ("vba", "activex", "embeddings", "externallink", "customui")):
            raise ParseValidationError(ParseErrorCode.UNSAFE, path, "active or external Office content is not accepted")
        if name.endswith(".rels") and b"TargetMode=\"External\"" in archive.read(info.filename):
            raise ParseValidationError(ParseErrorCode.UNSAFE, path, "external Office links are not accepted")
        if info.file_size > 20_000_000 or (info.compress_size and info.file_size / info.compress_size > 100):
            raise ParseValidationError(ParseErrorCode.RESOURCE_LIMIT, path, "Office entry exceeds safe expansion limits")


def _parse_docx(path: Path, archive: zipfile.ZipFile) -> tuple[ParsedRecord, ...]:
    try:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (KeyError, ElementTree.ParseError) as error:
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "DOCX document XML is invalid") from error
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    records: list[ParsedRecord] = []
    for index, paragraph in enumerate(root.iter(f"{namespace}p"), start=1):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
        if text:
            records.append(_record(path, f"{path.stem}:p:{index}", text, {"source_type": "docx"}, f"paragraph:{index}"))
    if not records:
        raise ParseValidationError(ParseErrorCode.SCANNED, path, "DOCX contains no selectable text")
    return tuple(records)


def _parse_xlsx(path: Path, archive: zipfile.ZipFile, limits: ParseLimits) -> tuple[ParsedRecord, ...]:
    try:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    except (KeyError, ElementTree.ParseError) as error:
        raise ParseValidationError(ParseErrorCode.MALFORMED, path, "XLSX workbook XML is invalid") from error
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    shared_strings = _read_shared_strings(archive, namespace)
    sheets = list(workbook.iter(f"{namespace}sheet"))
    if len(sheets) > limits.max_sheets:
        raise ParseValidationError(ParseErrorCode.RESOURCE_LIMIT, path, "XLSX sheet limit exceeded")
    records: list[ParsedRecord] = []
    cell_count = 0
    for sheet_index, sheet in enumerate(sheets, start=1):
        target = f"xl/worksheets/sheet{sheet_index}.xml"
        try:
            root = ElementTree.fromstring(archive.read(target))
        except (KeyError, ElementTree.ParseError) as error:
            raise ParseValidationError(ParseErrorCode.MALFORMED, path, "XLSX worksheet XML is invalid") from error
        for row in root.iter(f"{namespace}row"):
            values = []
            references = []
            for cell in row.iter(f"{namespace}c"):
                cell_count += 1
                if cell_count > limits.max_cells:
                    raise ParseValidationError(ParseErrorCode.RESOURCE_LIMIT, path, "XLSX cell limit exceeded")
                references.append(cell.attrib.get("r", "unknown"))
                value_node = cell.find(f"{namespace}v")
                inline_node = cell.find(f"{namespace}is/{namespace}t")
                value = (
                    value_node.text if value_node is not None else inline_node.text if inline_node is not None else ""
                ) or ""
                if cell.attrib.get("t") == "s" and value.isdigit() and int(value) < len(shared_strings):
                    value = shared_strings[int(value)]
                values.append(value)
            text = " | ".join(value for value in values if value).strip()
            if text:
                sheet_name = sheet.attrib.get("name", f"sheet{sheet_index}")
                locator = f"sheet:{sheet_name}!{','.join(references)}"
                records.append(_record(path, f"{path.stem}:{locator}", text, {"source_type": "xlsx", "sheet": sheet_name}, locator))
    if not records:
        raise ParseValidationError(ParseErrorCode.SCANNED, path, "XLSX contains no selectable cell text")
    return tuple(records)


def _read_shared_strings(archive: zipfile.ZipFile, namespace: str) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    except ElementTree.ParseError:
        return []
    return ["".join(node.text or "" for node in item.iter(f"{namespace}t")) for item in root]


def _stringify(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")
