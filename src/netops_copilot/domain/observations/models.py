"""不可变的告警和健康观测模型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from netops_copilot.domain.inventory import DeviceId, InterfaceName, SiteId
from netops_copilot.domain.shared.time import require_utc


class AlarmSeverity(StrEnum):
    """运维告警严重级别。"""

    INFO = "info"
    WARNING = "warning"
    MAJOR = "major"
    CRITICAL = "critical"


class HealthStatus(StrEnum):
    """粗粒度的只读设备健康状态。"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AlarmEvent:
    """不可变的来源告警，其事实不能被 LLM 改写。"""

    alarm_id: str
    device_id: DeviceId
    site_id: SiteId
    code: str
    severity: AlarmSeverity
    raised_at: datetime
    summary: str
    interface: InterfaceName | None = None
    cleared_at: datetime | None = None
    scenario_id: str | None = None
    synthetic: bool = True

    def __post_init__(self) -> None:
        if not self.alarm_id.strip() or not self.code.strip() or not self.summary.strip():
            raise ValueError("alarm id, code and summary cannot be empty")
        raised_at = require_utc(self.raised_at)
        object.__setattr__(self, "raised_at", raised_at)
        if self.cleared_at is not None:
            cleared_at = require_utc(self.cleared_at)
            if cleared_at < raised_at:
                raise ValueError("cleared_at cannot precede raised_at")
            object.__setattr__(self, "cleared_at", cleared_at)


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """带时间戳且数值指标不可变的健康读数。"""

    snapshot_id: str
    device_id: DeviceId
    captured_at: datetime
    status: HealthStatus
    metrics: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("health snapshot id cannot be empty")
        object.__setattr__(self, "captured_at", require_utc(self.captured_at))
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
