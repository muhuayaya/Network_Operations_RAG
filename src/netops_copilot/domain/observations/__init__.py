"""只读设备观测。"""

from netops_copilot.domain.observations.models import (
    AlarmEvent,
    AlarmSeverity,
    HealthSnapshot,
    HealthStatus,
)

__all__ = ["AlarmEvent", "AlarmSeverity", "HealthSnapshot", "HealthStatus"]
