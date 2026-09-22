"""确定性配置差异比较和风险分类。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from netops_copilot.domain.configurations import ChangeOperation, ConfigChange, RiskLevel
from netops_copilot.domain.inventory import Vendor
from netops_copilot.infrastructure.configuration import (
    CommandFamily,
    NormalizedConfigLine,
    NormalizedConfiguration,
    normalize_configuration,
)


class ConfigurationDiffError(ValueError):
    """两个快照无法安全比较时抛出的异常。"""


@dataclass(frozen=True, slots=True)
class ConfigurationDiff:
    """比较两个规范化快照后得到的稳定结构化结果。"""

    vendor: Vendor
    changes: tuple[ConfigChange, ...]

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    @property
    def risk_level(self) -> RiskLevel:
        if any(change.risk_level is RiskLevel.HIGH for change in self.changes):
            return RiskLevel.HIGH
        if any(change.risk_level is RiskLevel.MEDIUM for change in self.changes):
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


class ConfigurationDiffer:
    """按确定性的语义路径比较配置行。"""

    def diff(
        self,
        baseline: str | NormalizedConfiguration,
        current: str | NormalizedConfiguration,
        *,
        vendor: Vendor | str | None = None,
    ) -> ConfigurationDiff:
        before = _as_normalized(baseline, vendor)
        after = _as_normalized(current, vendor or before.vendor)
        if before.vendor is not after.vendor:
            raise ConfigurationDiffError("baseline and current vendors must match")

        before_by_key = _group_lines(before.lines)
        after_by_key = _group_lines(after.lines)
        keys = sorted(set(before_by_key) | set(after_by_key))
        changes: list[ConfigChange] = []
        for key in keys:
            changes.extend(_diff_key(key, before_by_key.get(key, ()), after_by_key.get(key, ())))
        return ConfigurationDiff(before.vendor, tuple(changes))


def diff_configurations(
    baseline: str | NormalizedConfiguration,
    current: str | NormalizedConfiguration,
    *,
    vendor: Vendor | str | None = None,
) -> ConfigurationDiff:
    """执行确定性配置比较的便捷函数。"""
    return ConfigurationDiffer().diff(baseline, current, vendor=vendor)


def _as_normalized(
    value: str | NormalizedConfiguration,
    vendor: Vendor | str | None,
) -> NormalizedConfiguration:
    if isinstance(value, NormalizedConfiguration):
        if vendor is not None:
            expected = _vendor_value(vendor)
            if value.vendor is not expected:
                raise ConfigurationDiffError("provided vendor does not match normalized configuration")
        return value
    if vendor is None:
        raise ConfigurationDiffError("vendor is required for raw configuration text")
    return normalize_configuration(vendor, value)


def _vendor_value(value: Vendor | str) -> Vendor:
    if isinstance(value, Vendor):
        return value
    return normalize_configuration(value, "interface Eth1").vendor


def _group_lines(lines: Iterable[NormalizedConfigLine]) -> dict[tuple[str, str], tuple[NormalizedConfigLine, ...]]:
    grouped: defaultdict[tuple[str, str], list[NormalizedConfigLine]] = defaultdict(list)
    for line in lines:
        grouped[(line.command_family.value, line.path)].append(line)
    return {key: tuple(value) for key, value in grouped.items()}


def _diff_key(
    key: tuple[str, str],
    before: tuple[NormalizedConfigLine, ...],
    after: tuple[NormalizedConfigLine, ...],
) -> list[ConfigChange]:
    family_name, path = key
    family = CommandFamily(family_name)
    changes: list[ConfigChange] = []
    paired = min(len(before), len(after))
    for index in range(paired):
        old = before[index]
        new = after[index]
        if old.canonical == new.canonical:
            continue
        operation = ChangeOperation.RAW if not old.known or not new.known else ChangeOperation.MODIFY
        changes.append(_change(family, path, operation, old, new))
    for old in before[paired:]:
        operation = ChangeOperation.RAW if not old.known else ChangeOperation.REMOVE
        changes.append(_change(family, path, operation, old, None))
    for new in after[paired:]:
        operation = ChangeOperation.RAW if not new.known else ChangeOperation.ADD
        changes.append(_change(family, path, operation, None, new))
    return changes


def _change(
    family: CommandFamily,
    path: str,
    operation: ChangeOperation,
    before: NormalizedConfigLine | None,
    after: NormalizedConfigLine | None,
) -> ConfigChange:
    risk_level, risk_tags = _risk(family, path, operation)
    refs = tuple(line.line_no for line in (before, after) if line is not None)
    return ConfigChange(
        section=family.value,
        path=path,
        operation=operation,
        before=before.canonical if before is not None else None,
        after=after.canonical if after is not None else None,
        line_refs=refs,
        risk_tags=risk_tags,
        risk_level=risk_level,
    )


def _risk(
    family: CommandFamily,
    path: str,
    operation: ChangeOperation,
) -> tuple[RiskLevel, tuple[str, ...]]:
    if family is CommandFamily.ACL:
        return RiskLevel.HIGH, ("acl-change", "traffic-affecting")
    if family is CommandFamily.VLAN:
        return RiskLevel.HIGH, ("vlan-change", "traffic-affecting")
    if family is CommandFamily.LACP:
        return RiskLevel.HIGH, ("lacp-change", "link-state")
    if family is CommandFamily.INTERFACE:
        if path.endswith("/shutdown") or operation is ChangeOperation.REMOVE:
            return RiskLevel.HIGH, ("interface-change", "link-state")
        return RiskLevel.MEDIUM, ("interface-change",)
    if family is CommandFamily.OSPF:
        return RiskLevel.MEDIUM, ("ospf-change", "routing-impact")
    return RiskLevel.LOW, ("unclassified-change",)
