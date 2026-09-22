"""风险感知建议安全契约。"""

from __future__ import annotations

import unittest

from netops_copilot.application import (
    ReadOnlyVerification,
    RecommendationValidationError,
    RiskAwareSuggestion,
    suggestion_for_change,
)
from netops_copilot.domain.configurations import ChangeOperation, ConfigChange, RiskLevel


class RecommendationTests(unittest.TestCase):
    def test_traffic_affecting_acl_suggestion_is_high_risk_and_human_controlled(self) -> None:
        change = ConfigChange(
            section="acl",
            path="acl/rule/10",
            operation=ChangeOperation.MODIFY,
            before="acl rule 10 permit ip",
            after="acl rule 10 deny ip",
            line_refs=(2, 2),
            risk_tags=("acl-change", "traffic-affecting"),
            risk_level=RiskLevel.HIGH,
        )

        suggestion = suggestion_for_change(change)

        self.assertEqual(suggestion.risk_level, RiskLevel.HIGH)
        self.assertTrue(suggestion.traffic_affecting)
        self.assertTrue(suggestion.human_controlled)
        self.assertTrue(suggestion.read_only_verification[0].command.startswith("show "))
        self.assertTrue(suggestion.rollback_plan)

    def test_routing_impact_is_promoted_to_high_for_suggestions(self) -> None:
        change = ConfigChange(
            section="ospf",
            path="ospf/area",
            operation=ChangeOperation.MODIFY,
            before="ospf area 0",
            after="ospf area 1",
            line_refs=(2, 2),
            risk_tags=("ospf-change", "routing-impact"),
            risk_level=RiskLevel.MEDIUM,
        )
        suggestion = suggestion_for_change(change)
        self.assertEqual(suggestion.risk_level, RiskLevel.HIGH)
        self.assertTrue(suggestion.traffic_affecting)

    def test_safety_controls_cannot_be_omitted_or_used_to_execute_changes(self) -> None:
        with self.assertRaises(RecommendationValidationError):
            ReadOnlyVerification("configure terminal", "not read only")
        with self.assertRaises(RecommendationValidationError):
            RiskAwareSuggestion(
                action="change acl",
                risk_level=RiskLevel.MEDIUM,
                prerequisites=("approved",),
                read_only_verification=(ReadOnlyVerification("show access-list", "check"),),
                escalation_conditions=("owner",),
                rollback_plan=("restore",),
                traffic_affecting=True,
                requires_human_approval=False,
            )


if __name__ == "__main__":
    unittest.main()
