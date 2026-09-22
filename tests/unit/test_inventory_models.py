"""不可变资产和拓扑模型测试。"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from netops_copilot.domain.inventory import (
    Device,
    DeviceId,
    DeviceRole,
    InterfaceName,
    LinkType,
    OsFamily,
    SiteId,
    TopologyLink,
    Vendor,
)


class InventoryModelTests(unittest.TestCase):
    """校验厂商身份和拓扑不变量。"""

    def test_device_is_immutable_and_has_unique_interfaces(self) -> None:
        device = Device(
            DeviceId("hw-01"),
            Vendor.HUAWEI,
            "S6730-H",
            OsFamily.VRP,
            "V200R022",
            DeviceRole.CORE,
            SiteId("site-sz-hq"),
            (InterfaceName("XGE1/0/49"),),
        )

        with self.assertRaises((AttributeError, TypeError)):
            device.model = "changed"  # type: ignore[misc]  # 验证不可变模型会拒绝赋值。
        with self.assertRaises(ValueError):
            Device(
                DeviceId("hw-02"),
                Vendor.HUAWEI,
                "S6730-H",
                OsFamily.VRP,
                "V200R022",
                DeviceRole.CORE,
                SiteId("site-sz-hq"),
                (InterfaceName("GE1/0/1"), InterfaceName("GE1/0/1")),
            )

    def test_topology_link_rejects_invalid_interval_and_supports_utc_lookup(self) -> None:
        start = datetime(2026, 9, 1, tzinfo=UTC)
        link = TopologyLink(
            "link-1",
            DeviceId("hw-01"),
            InterfaceName("XGE1/0/49"),
            DeviceId("h3c-01"),
            InterfaceName("XGE1/0/50"),
            LinkType.ETHERNET,
            start,
            start + timedelta(days=1),
        )

        self.assertTrue(link.contains(start + timedelta(hours=1)))
        with self.assertRaises(ValueError):
            TopologyLink(
                "invalid",
                DeviceId("hw-01"),
                InterfaceName("XGE1/0/49"),
                DeviceId("hw-01"),
                InterfaceName("XGE1/0/49"),
                LinkType.ETHERNET,
                start,
            )
        with self.assertRaises(ValueError):
            TopologyLink(
                "invalid-time",
                DeviceId("hw-01"),
                InterfaceName("XGE1/0/49"),
                DeviceId("h3c-01"),
                InterfaceName("XGE1/0/50"),
                LinkType.ETHERNET,
                start,
                start - timedelta(seconds=1),
            )
