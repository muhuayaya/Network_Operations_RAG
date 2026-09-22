"""只读设备观测端口。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from netops_copilot.domain.configurations import ConfigSnapshot
from netops_copilot.domain.inventory import Device, DeviceId
from netops_copilot.domain.observations import AlarmEvent, HealthSnapshot


class DeviceObservationNotFound(LookupError):
    """请求的模拟设备观测不可用。"""


class DeviceObservationPort(Protocol):
    """仅包含事实的设备上下文；不提供变更和任意命令。"""

    def get_inventory(self, device_id: DeviceId | str) -> Device:
        """读取稳定资产清单。"""

    def get_facts(self, device_id: DeviceId | str) -> Mapping[str, str]:
        """读取规范化事实。"""

    def get_configuration(self, device_id: DeviceId | str) -> ConfigSnapshot:
        """读取活动配置快照。"""

    def get_health(self, device_id: DeviceId | str) -> HealthSnapshot:
        """读取最新健康快照。"""

    def get_alarms(self, device_id: DeviceId | str) -> tuple[AlarmEvent, ...]:
        """读取来源告警，但不执行变更。"""
