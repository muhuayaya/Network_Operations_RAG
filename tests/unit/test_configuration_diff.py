"""确定性配置差异和风险规则测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.config_diff import ConfigurationDiffError, diff_configurations
from netops_copilot.domain.configurations import ChangeOperation, RiskLevel
from netops_copilot.domain.inventory import Vendor


class ConfigurationDiffTests(unittest.TestCase):
    def test_acl_fixture_emits_structured_high_risk_modify(self) -> None:
        baseline = """acl number 3001
 rule 10 permit ip source 10.0.0.0 0.0.0.255
 rule 20 deny ip
"""
        current = """acl number 3001
 rule 10 deny ip source 10.0.0.0 0.0.0.255
 rule 20 deny ip
 rule 30 permit ip destination 10.0.2.0 0.0.0.255
"""

        result = diff_configurations(baseline, current, vendor=Vendor.HUAWEI)

        self.assertEqual(len(result.changes), 2)
        self.assertEqual(result.changes[0].operation, ChangeOperation.MODIFY)
        self.assertEqual(result.changes[0].section, "acl")
        self.assertEqual(result.changes[0].path, "acl/rule/10")
        self.assertEqual(result.changes[0].risk_level, RiskLevel.HIGH)
        self.assertEqual(result.changes[0].line_refs, (2, 2))
        self.assertEqual(result.changes[1].operation, ChangeOperation.ADD)
        self.assertEqual(result.risk_level, RiskLevel.HIGH)

    def test_interface_vlan_lacp_and_ospf_changes_have_deterministic_risks(self) -> None:
        baseline = """interface GigabitEthernet1/0/1
 description old
 port default vlan 10
 channel-group 1 mode active
 ospf enable 1 area 0
"""
        current = """interface GigabitEthernet1/0/1
 description new
 port default vlan 20
 channel-group 2 mode active
 ospf enable 1 area 1
"""

        result = diff_configurations(baseline, current, vendor="huawei")

        self.assertEqual({change.section for change in result.changes}, {"interface", "lacp", "ospf", "vlan"})
        by_section = {change.section: change for change in result.changes}
        self.assertEqual(by_section["interface"].risk_level, RiskLevel.MEDIUM)
        self.assertEqual(by_section["vlan"].risk_level, RiskLevel.HIGH)
        self.assertEqual(by_section["lacp"].risk_level, RiskLevel.HIGH)
        self.assertEqual(by_section["ospf"].risk_level, RiskLevel.MEDIUM)

    def test_unknown_line_is_raw_and_same_snapshots_are_empty(self) -> None:
        content = "interface Eth1\n totally vendor-specific syntax\n"
        result = diff_configurations(content, content, vendor=Vendor.CISCO)
        self.assertFalse(result.changed)
        self.assertEqual(result.changes, ())

        changed = diff_configurations(content, "interface Eth1\n another unknown command\n", vendor=Vendor.CISCO)
        self.assertEqual(changed.changes[0].operation, ChangeOperation.RAW)
        self.assertEqual(changed.changes[0].section, "raw")

    def test_raw_text_requires_vendor_and_normalized_vendors_must_match(self) -> None:
        with self.assertRaises(ConfigurationDiffError):
            diff_configurations("interface Eth1", "interface Eth1")


if __name__ == "__main__":
    unittest.main()
