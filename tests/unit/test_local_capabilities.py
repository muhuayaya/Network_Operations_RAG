"""预留本地 provider 可用性和降级测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.local_capabilities import (
    LocalCapabilityStatus,
    automatic_fallback,
    local_capability_report,
)
from netops_copilot.application.ports.providers import ProviderHealth, ProviderKind
from netops_copilot.bootstrap import bootstrap, create_builtin_registry
from netops_copilot.settings import ProfileName


class LocalCapabilityTests(unittest.TestCase):
    def test_reserved_local_profile_is_reported_unavailable(self) -> None:
        settings = bootstrap(ProfileName.TEST).settings
        report = local_capability_report(settings)
        self.assertEqual({item.status for item in report}, {LocalCapabilityStatus.RESERVED_UNAVAILABLE})
        local_descriptor = create_builtin_registry().create(
            ProviderKind.EMBEDDING, "local-reserved", settings
        )
        self.assertEqual(local_descriptor.health, ProviderHealth.RESERVED)
        self.assertFalse(local_descriptor.is_usable)

    def test_reserved_provider_is_not_an_automatic_fallback(self) -> None:
        settings = bootstrap(ProfileName.TEST).settings
        reserved = create_builtin_registry().create(ProviderKind.LLM, "local-reserved", settings)
        self.assertIsNone(automatic_fallback([reserved]))
