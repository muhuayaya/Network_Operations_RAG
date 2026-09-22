"""知识来源、分块和引用溯源模型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from netops_copilot.domain.inventory import DataSecurityLevel
from netops_copilot.domain.shared.time import require_utc


class SourceType(StrEnum):
    """支持的知识来源类别。"""

    MANUAL = "manual"
    SOP = "sop"
    TICKET = "ticket"
    ALARM = "alarm"
    CONFIGURATION = "configuration"
    TOPOLOGY = "topology"


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """使每个分块都能追溯到来源的来源记录。"""

    source_id: str
    source_type: SourceType
    title: str
    version: str
    effective_at: datetime
    security_level: DataSecurityLevel
    source_locator: str
    content_hash: str
    vendor: str | None = None
    site_id: str | None = None
    device_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("source_id", "title", "version", "source_locator", "content_hash"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be empty")
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """Dense 和 Lexical 索引共享的稳定可引用单元。"""

    chunk_id: str
    source_id: str
    version: str
    text: str
    source_locator: str
    content_hash: str
    security_level: DataSecurityLevel
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        for field_name in ("chunk_id", "source_id", "version", "source_locator", "content_hash"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be empty")
        if not self.text.strip():
            raise ValueError("chunk text cannot be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class Citation:
    """对一个已授权知识分块的有边界引用。"""

    chunk_id: str
    source_id: str
    source_locator: str

    def __post_init__(self) -> None:
        if not self.chunk_id.strip() or not self.source_id.strip() or not self.source_locator.strip():
            raise ValueError("citation provenance fields cannot be empty")
