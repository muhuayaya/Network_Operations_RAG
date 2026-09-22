"""结构化且由人工控制的运维建议。"""

from __future__ import annotations

from dataclasses import dataclass

from netops_copilot.domain.configurations import ConfigChange, RiskLevel


class RecommendationValidationError(ValueError):
    """建议缺少必需安全控制时抛出的异常。"""


@dataclass(frozen=True, slots=True)
class ReadOnlyVerification:
    """仅用于描述的验证步骤，本服务绝不执行它。"""

    command: str
    purpose: str

    def __post_init__(self) -> None:
        if not self.command.strip() or not self.purpose.strip():
            raise RecommendationValidationError("read-only verification requires command and purpose")
        lowered = self.command.lower()
        if any(token in lowered.split() for token in ("configure", "commit", "write", "delete")):
            raise RecommendationValidationError("verification command must remain read-only")


@dataclass(frozen=True, slots=True)
class RiskAwareSuggestion:
    """包含明确人工控制和回滚控制的建议契约。"""

    action: str
    risk_level: RiskLevel
    prerequisites: tuple[str, ...]
    read_only_verification: tuple[ReadOnlyVerification, ...]
    escalation_conditions: tuple[str, ...]
    rollback_plan: tuple[str, ...]
    traffic_affecting: bool = False
    requires_human_approval: bool = True

    def __post_init__(self) -> None:
        if not self.action.strip():
            raise RecommendationValidationError("suggestion action cannot be empty")
        if not self.prerequisites or any(not item.strip() for item in self.prerequisites):
            raise RecommendationValidationError("suggestion requires non-empty prerequisites")
        if not self.read_only_verification:
            raise RecommendationValidationError("suggestion requires read-only verification")
        if not self.escalation_conditions or any(not item.strip() for item in self.escalation_conditions):
            raise RecommendationValidationError("suggestion requires escalation conditions")
        if not self.rollback_plan or any(not item.strip() for item in self.rollback_plan):
            raise RecommendationValidationError("suggestion requires rollback plan")
        if self.traffic_affecting and self.risk_level is not RiskLevel.HIGH:
            raise RecommendationValidationError("traffic-affecting suggestions must be high risk")
        if self.traffic_affecting and not self.requires_human_approval:
            raise RecommendationValidationError("traffic-affecting suggestions require human approval")

    @property
    def human_controlled(self) -> bool:
        """面向使用人工控制表述的 API 调用方的显式别名。"""
        return self.requires_human_approval


def suggestion_for_change(change: ConfigChange) -> RiskAwareSuggestion:
    """根据确定性差异事实构建安全且不可执行的建议。"""
    traffic_affecting = bool(set(change.risk_tags) & {"traffic-affecting", "link-state", "routing-impact"})
    risk_level = RiskLevel.HIGH if traffic_affecting else change.risk_level
    family = change.section
    return RiskAwareSuggestion(
        action=f"Review {family} change at {change.path} before any implementation.",
        risk_level=risk_level,
        prerequisites=("Confirm the device, site, maintenance window and approved baseline.",),
        read_only_verification=(
            ReadOnlyVerification(
                command=_verification_command(family),
                purpose=f"Verify the current {family} state before human review.",
            ),
        ),
        escalation_conditions=(
            "Escalate to the network owner if the observed state differs from the approved change.",
        ),
        rollback_plan=(
            "Retain the baseline snapshot and prepare a human-reviewed restoration plan; do not execute automatically.",
        ),
        traffic_affecting=traffic_affecting,
        requires_human_approval=True,
    )


def _verification_command(family: str) -> str:
    return {
        "acl": "show access-list",
        "interface": "show interfaces",
        "vlan": "show vlan",
        "lacp": "show lacp neighbors",
        "ospf": "show ospf neighbor",
    }.get(family, "show running-state")
