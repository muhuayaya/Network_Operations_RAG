"""跨厂商无损配置规范化测试。"""

from __future__ import annotations

import unittest

from netops_copilot.domain.inventory import Vendor
from netops_copilot.infrastructure.configuration import (
    ConfigurationNormalizationError,
    normalize_configuration,
)


class ConfigurationNormalizerTests(unittest.TestCase):
    def test_huawei_h3c_and_ruijie_ospf_and_interface_syntax_share_concepts(self) -> None:
        samples = (
            (Vendor.HUAWEI, "interface GE1/0/1\n ospf enable 1 area 0.0.0.0\n"),
            (Vendor.H3C, "interface GigabitEthernet1/0/1\n ospf 1 area 0.0.0.0\n"),
            (Vendor.RUIJIE, "interface GigabitEthernet 1/0/1\n ip ospf 1 area 0\n"),
        )

        normalized = [normalize_configuration(vendor, content) for vendor, content in samples]

        self.assertEqual(normalized[0].lines[0].canonical, "interface ethernet1/0/1")
        self.assertEqual(normalized[1].lines[0].canonical, "interface ethernet1/0/1")
        self.assertEqual(normalized[2].lines[0].canonical, "interface ethernet1/0/1")
        self.assertEqual(normalized[0].lines[1].canonical, "ospf area 0.0.0.0")
        self.assertEqual(normalized[1].lines[1].canonical, "ospf area 0.0.0.0")
        self.assertEqual(normalized[2].lines[1].canonical, "ospf area 0")

    def test_vendor_aggregation_and_acl_commands_are_normalized(self) -> None:
        content = (
            "interface Eth-Trunk10\n"
            " lacp timeout short\n"
            "interface GigabitEthernet0/0/1\n"
            " channel-group 10 mode active\n"
            " ip access-group 3001 in\n"
            "acl number 3001\n"
            " rule 10 deny ip source 10.0.0.0 0.0.0.255\n"
        )
        normalized = normalize_configuration(Vendor.HUAWEI, content)

        canonical = normalized.canonical_lines
        self.assertIn("interface port-channel10", canonical)
        self.assertIn("lacp timeout short", canonical)
        self.assertIn("lacp group 10 mode active", canonical)
        self.assertIn("acl apply 3001 in", canonical)
        self.assertIn("acl 3001", canonical)
        self.assertIn("acl rule 10 deny ip source 10.0.0.0 0.0.0.255", canonical)

    def test_cisco_concept_mapping_and_unknown_lines_are_lossless(self) -> None:
        content = (
            "interface Port-channel10\n"
            " channel-group 10 mode active\n"
            " ip access-group EDGE-IN in\n"
            "router ospf 1\n"
            " network 10.0.0.0 0.0.0.255 area 0\n"
            " totally vendor-specific syntax\n"
        )
        normalized = normalize_configuration("cisco-compatible", content)

        self.assertEqual(normalized.vendor, Vendor.CISCO)
        self.assertEqual(normalized.lines[0].canonical, "interface port-channel10")
        self.assertEqual(normalized.lines[1].canonical, "lacp group 10 mode active")
        self.assertEqual(normalized.lines[2].canonical, "acl apply EDGE-IN in")
        self.assertEqual(normalized.lines[4].canonical, "ospf network 10.0.0.0 0.0.0.255 area 0")
        unknown = normalized.lines[-1]
        self.assertFalse(unknown.known)
        self.assertEqual(unknown.raw, " totally vendor-specific syntax")
        self.assertEqual(unknown.section, "raw")
        self.assertEqual(unknown.parent_section, "ospf/1")
        self.assertEqual(normalized.content.splitlines()[-1], "totally vendor-specific syntax")

    def test_invalid_vendor_and_empty_content_fail_closed(self) -> None:
        with self.assertRaises(ConfigurationNormalizationError):
            normalize_configuration("unknown", "interface Eth1")
        with self.assertRaises(ConfigurationNormalizationError):
            normalize_configuration(Vendor.HUAWEI, "\n")


if __name__ == "__main__":
    unittest.main()
