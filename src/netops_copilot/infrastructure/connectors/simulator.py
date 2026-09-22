"""确定性的只读设备观测模拟器。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from netops_copilot.application.ports.device import DeviceObservationNotFound
from netops_copilot.domain.configurations import ConfigSnapshot
from netops_copilot.domain.inventory import Device, DeviceId
from netops_copilot.domain.observations import AlarmEvent, HealthSnapshot


class SimulatorDeviceObservation:
    """只暴露读取方法的内存事实存储。"""

    def __init__(
        self,
        inventory: Sequence[Device] = (),
        facts: Mapping[str, Mapping[str, str]] | None = None,
        configurations: Sequence[ConfigSnapshot] = (),
        health: Sequence[HealthSnapshot] = (),
        alarms: Sequence[AlarmEvent] = (),
    ) -> None:
        self._inventory = {str(device.device_id): device for device in inventory}
        self._facts = {key: MappingProxyType(dict(value)) for key, value in (facts or {}).items()}
        self._configurations = {str(snapshot.device_id): snapshot for snapshot in configurations}
        self._health = {str(snapshot.device_id): snapshot for snapshot in health}
        self._alarms: dict[str, tuple[AlarmEvent, ...]] = {
            str(device.device_id): () for device in inventory
        }
        for alarm in alarms:
            self._alarms.setdefault(str(alarm.device_id), ())
            self._alarms[str(alarm.device_id)] = self._alarms[str(alarm.device_id)] + (alarm,)

    def get_inventory(self, device_id: DeviceId | str) -> Device:
        try:
            return self._inventory[str(device_id)]
        except KeyError as error:
            raise DeviceObservationNotFound(str(device_id)) from error

    def get_facts(self, device_id: DeviceId | str) -> Mapping[str, str]:
        try:
            return self._facts[str(device_id)]
        except KeyError as error:
            raise DeviceObservationNotFound(str(device_id)) from error

    def get_configuration(self, device_id: DeviceId | str) -> ConfigSnapshot:
        try:
            return self._configurations[str(device_id)]
        except KeyError as error:
            raise DeviceObservationNotFound(str(device_id)) from error

    def get_health(self, device_id: DeviceId | str) -> HealthSnapshot:
        try:
            return self._health[str(device_id)]
        except KeyError as error:
            raise DeviceObservationNotFound(str(device_id)) from error

    def get_alarms(self, device_id: DeviceId | str) -> tuple[AlarmEvent, ...]:
        try:
            return self._alarms[str(device_id)]
        except KeyError as error:
            raise DeviceObservationNotFound(str(device_id)) from error
