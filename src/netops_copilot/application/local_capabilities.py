"""不可用本地 provider 的显式报告和选择规则。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from netops_copilot.application.ports.providers import (
    ProviderDescriptor,
    ProviderHealth,
    ProviderKind,
)
from netops_copilot.settings import ProfileSettings


class LocalCapabilityStatus(StrEnum):
    """诊断中显示的可用状态，不等同于已就绪。"""

    RESERVED_UNAVAILABLE = "reserved-unavailable"
    AVAILABLE = "available"


@dataclass(frozen=True, slots=True)
class LocalCapabilityReport:
    """一条本地能力诊断记录。"""

    kind: ProviderKind
    provider: str
    status: LocalCapabilityStatus
    detail: str


def local_capability_report(settings: ProfileSettings) -> tuple[LocalCapabilityReport, ...]:
    """报告 Profile 的预留本地路径，但不解析具体实现。"""
    status = (
        LocalCapabilityStatus.AVAILABLE
        if settings.local_model.available
        else LocalCapabilityStatus.RESERVED_UNAVAILABLE
    )
    detail = "configured local provider is unavailable" if status is LocalCapabilityStatus.RESERVED_UNAVAILABLE else "available"
    return (
        LocalCapabilityReport(ProviderKind.LLM, settings.local_model.provider, status, detail),
        LocalCapabilityReport(ProviderKind.EMBEDDING, settings.local_model.provider, status, detail),
    )


def automatic_fallback(candidates: Iterable[ProviderDescriptor]) -> ProviderDescriptor | None:
    """只选择可用且非预留的 provider；绝不自动选择 local-reserved。"""
    for descriptor in candidates:
        if descriptor.health is not ProviderHealth.RESERVED and descriptor.is_usable:
            return descriptor
    return None
