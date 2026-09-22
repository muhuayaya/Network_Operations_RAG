"""由组合根拥有的显式 provider 工厂注册表。"""

from __future__ import annotations

from collections.abc import Callable

from netops_copilot.application.ports.providers import ProviderDescriptor, ProviderKind
from netops_copilot.settings import ProfileSettings

ProviderFactory = Callable[[ProfileSettings], ProviderDescriptor]


class ProviderRegistry:
    """从 provider 角色和名称映射到工厂的确定性映射。"""

    def __init__(self) -> None:
        self._factories: dict[tuple[ProviderKind, str], ProviderFactory] = {}

    def register(self, kind: ProviderKind, provider: str, factory: ProviderFactory) -> None:
        """显式注册 provider，并拒绝意外替换。"""
        key = (kind, provider)
        if key in self._factories:
            raise ValueError(f"provider already registered: {kind.value}:{provider}")
        self._factories[key] = factory

    def create(self, kind: ProviderKind, provider: str, settings: ProfileSettings) -> ProviderDescriptor:
        """为选定的 provider 构造描述符。"""
        try:
            return self._factories[(kind, provider)](settings)
        except KeyError as error:
            raise ValueError(f"provider is not registered: {kind.value}:{provider}") from error

    def provider_ids(self) -> tuple[str, ...]:
        """按确定性的角色/名称顺序列出已注册 provider。"""
        return tuple(
            f"{kind.value}:{provider}"
            for kind, provider in sorted(self._factories, key=lambda item: (item[0].value, item[1]))
        )
