"""按来源类型确定性切分，并生成稳定 ID 和内容哈希。"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from netops_copilot.infrastructure.ingestion.parsers import ParsedRecord


class ChunkingError(ValueError):
    """来源无法生成有意义分块时抛出的异常。"""


@dataclass(frozen=True, slots=True)
class ChunkingPolicy:
    """有边界的确定性切分控制参数。"""

    max_chars: int = 800

    def __post_init__(self) -> None:
        if self.max_chars < 32:
            raise ValueError("max_chars must be at least 32")


@dataclass(frozen=True, slots=True)
class KnowledgeChunkRecord:
    """包含引用定位和来源溯源、可持久化的分块。"""

    chunk_id: str
    source_id: str
    ordinal: int
    text: str
    source_locator: str
    content_hash: str
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.ordinal < 0 or not self.text.strip():
            raise ValueError("chunk ordinal and text must be valid")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def chunk_record(record: ParsedRecord, policy: ChunkingPolicy | None = None) -> tuple[KnowledgeChunkRecord, ...]:
    """使用规范化来源类型元数据切分已解析记录。"""
    policy = policy or ChunkingPolicy()
    source_type = record.metadata.get("source_type", "manual").lower()
    if source_type in {"manual", "markdown", "vendor_reference", "sop"}:
        units = _manual_units(record.content)
    elif source_type in {"ticket", "alarm"}:
        units = _paragraph_units(record.content)
    elif source_type in {"configuration", "config"}:
        units = _configuration_units(record.content)
    else:
        units = _paragraph_units(record.content)
    packed = _pack(units, policy.max_chars)
    if not packed:
        raise ChunkingError(f"source {record.source_id} produced no chunks")
    chunks = []
    for ordinal, text in enumerate(packed):
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        stable_key = f"{record.source_id}:{record.parser_version}:{ordinal}:{content_hash}"
        chunk_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:24]
        chunks.append(
            KnowledgeChunkRecord(
                chunk_id=chunk_id,
                source_id=record.source_id,
                ordinal=ordinal,
                text=text,
                source_locator=f"{record.location.locator}#chunk:{ordinal}",
                content_hash=content_hash,
                metadata=record.metadata,
            )
        )
    return tuple(chunks)


def _manual_units(text: str) -> list[str]:
    headings: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") and current:
            headings.append("\n".join(current).strip())
            current = []
        if line.strip():
            current.append(line.rstrip())
    if current:
        headings.append("\n".join(current).strip())
    return headings


def _paragraph_units(text: str) -> list[str]:
    return [unit.strip() for unit in re.split(r"\n\s*\n", text) if unit.strip()]


def _configuration_units(text: str) -> list[str]:
    units: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        starts_section = bool(
            line
            and not line[0].isspace()
            and re.match(r"(?:interface|router|vlan|acl|system|hostname)\b", line, re.IGNORECASE)
        )
        if starts_section and current:
            units.append("\n".join(current).strip())
            current = []
        if line.strip():
            current.append(line.rstrip())
    if current:
        units.append("\n".join(current).strip())
    return units


def _pack(units: list[str], max_chars: int) -> list[str]:
    packed: list[str] = []
    for unit in units:
        if len(unit) > max_chars:
            packed.extend(unit[index : index + max_chars] for index in range(0, len(unit), max_chars))
        else:
            packed.append(unit)
    return packed
