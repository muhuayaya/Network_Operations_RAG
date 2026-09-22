"""不可变配置快照和确定性变更记录。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from netops_copilot.domain.inventory import DataSecurityLevel, DeviceId, SiteId, Vendor
from netops_copilot.domain.shared.time import require_utc


class ChangeOperation(StrEnum):
    """规范化配置变更操作。"""

    ADD = "add"
    REMOVE = "remove"
    MODIFY = "modify"
    RAW = "raw"


class RiskLevel(StrEnum):
    """供人工审核配置解释的风险级别。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """保留来源溯源的不可变配置快照。"""

    snapshot_id: str
    device_id: DeviceId
    site_id: SiteId
    vendor: Vendor
    captured_at: datetime
    revision: str
    content: str
    content_hash: str
    security_level: DataSecurityLevel
    parent_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("snapshot_id", "revision", "content_hash"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be empty")
        if not self.content.strip():
            raise ValueError("configuration content cannot be empty")
        object.__setattr__(self, "captured_at", require_utc(self.captured_at))


@dataclass(frozen=True, slots=True)
class ConfigChange:
    """两个快照之间的确定性规范化差异。"""

    section: str
    path: str
    operation: ChangeOperation
    before: str | None
    after: str | None
    line_refs: tuple[int, ...]
    risk_tags: tuple[str, ...]
    risk_level: RiskLevel = RiskLevel.LOW

    def __post_init__(self) -> None:
        if not self.section.strip() or not self.path.strip():
            raise ValueError("configuration change section and path cannot be empty")
        if any(line < 1 for line in self.line_refs):
            raise ValueError("configuration line references must be positive")
        if self.operation is ChangeOperation.ADD and self.after is None:
            raise ValueError("add change requires after content")
        if self.operation is ChangeOperation.REMOVE and self.before is None:
            raise ValueError("remove change requires before content")
