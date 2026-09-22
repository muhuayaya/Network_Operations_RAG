"""确定性告警关联规则和五类事故覆盖测试。"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from netops_copilot.application.correlation import AlarmCorrelator, IncidentSignal


class AlarmCorrelationTests(unittest.TestCase):
    def test_ospf_exstart_correlates_with_transparent_reasons(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        primary = IncidentSignal("ospf-exstart", "hw-01", now, "Eth1", "OSPF:ExStart", frozenset({"hw-02"}), frozenset({"router ospf"}), "OSPF neighbor ExStart")
        candidate = IncidentSignal("ospf-followup", "hw-01", now + timedelta(minutes=2), "Eth1", "OSPF:ExStart", frozenset({"hw-02"}), frozenset({"router ospf"}), "OSPF neighbor stuck")
        matches = AlarmCorrelator().correlate(primary, [candidate])
        self.assertEqual(matches[0].incident_id, "ospf-followup")
        self.assertIn("same-protocol-state", matches[0].reasons)
        self.assertIn("same-interface", matches[0].reasons)

    def test_all_five_incident_signals_receive_a_nonempty_correlation(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        signals = [
            IncidentSignal(f"incident-{index}", "hw-01", now + timedelta(minutes=index), text="uplink protocol alarm")
            for index in range(5)
        ]
        correlator = AlarmCorrelator()
        for primary in signals:
            self.assertTrue(correlator.correlate(primary, signals))
