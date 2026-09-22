"""只读模拟器适配器契约测试。"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from netops_copilot.domain.configurations import ConfigSnapshot
from netops_copilot.domain.inventory import (
    DataSecurityLevel,
    Device,
    DeviceId,
    DeviceRole,
    OsFamily,
    SiteId,
    Vendor,
)
from netops_copilot.domain.observations import HealthSnapshot, HealthStatus
from netops_copilot.infrastructure.connectors.simulator import SimulatorDeviceObservation


class DeviceObservationTests(unittest.TestCase):
    def setUp(self) -> None:
        device = Device(
            DeviceId("hw-01"),
            Vendor.HUAWEI,
            "S6730",
            OsFamily.VRP,
            "V1",
            DeviceRole.CORE,
            SiteId("site-gz-dc"),
            (),
        )
        snapshot = ConfigSnapshot(
            "cfg-1",
            DeviceId("hw-01"),
            SiteId("site-gz-dc"),
            Vendor.HUAWEI,
            datetime(2026, 1, 1, tzinfo=UTC),
            "v1",
            "hostname core",
            "hash",
            DataSecurityLevel.INTERNAL,
        )
        health = HealthSnapshot(
            "health-1",
            DeviceId("hw-01"),
            datetime(2026, 1, 1, tzinfo=UTC),
            HealthStatus.HEALTHY,
            {},
        )
        self.simulator = SimulatorDeviceObservation(
            [device], {"hw-01": {"model": "S6730"}}, [snapshot], [health]
        )

    def test_all_observation_reads_are_available(self) -> None:
        self.assertEqual(self.simulator.get_inventory("hw-01").vendor, Vendor.HUAWEI)
        self.assertEqual(self.simulator.get_facts("hw-01")["model"], "S6730")
        self.assertEqual(self.simulator.get_configuration("hw-01").revision, "v1")
        self.assertEqual(self.simulator.get_health("hw-01").status, HealthStatus.HEALTHY)
        self.assertEqual(self.simulator.get_alarms("hw-01"), ())
        public_names = set(dir(self.simulator))
        self.assertNotIn("set_configuration", public_names)
        self.assertNotIn("execute", public_names)
