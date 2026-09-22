"""显式组合根和 provider 注册表测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.ports.providers import ProviderKind
from netops_copilot.application.ports.registry import ProviderRegistry
from netops_copilot.bootstrap import bootstrap, create_builtin_registry
from netops_copilot.settings import ProfileName


class BootstrapTests(unittest.TestCase):
    """导入模块不会产生适配器注册副作用。"""

    def test_builtin_provider_ids_are_stable_and_sorted(self) -> None:
        first = create_builtin_registry().provider_ids()
        second = create_builtin_registry().provider_ids()

        self.assertEqual(first, second)
        self.assertEqual(first, tuple(sorted(first)))
        self.assertIn("llm:openai-compatible", first)
        self.assertIn("dense-search:chroma", first)

    def test_bootstrap_selects_only_profile_providers(self) -> None:
        container = bootstrap(ProfileName.TEST)

        self.assertEqual(container.settings.profile, ProfileName.TEST)
        self.assertEqual(
            tuple(descriptor.kind for descriptor in container.providers),
            (
                ProviderKind.LLM,
                ProviderKind.EMBEDDING,
                ProviderKind.DENSE_SEARCH,
                ProviderKind.LEXICAL_SEARCH,
                ProviderKind.METADATA_STORAGE,
                ProviderKind.DEVICE_OBSERVATION,
            ),
        )

    def test_registry_requires_explicit_registration(self) -> None:
        registry = ProviderRegistry()

        with self.assertRaisesRegex(ValueError, "not registered"):
            registry.create(ProviderKind.LLM, "fake", bootstrap(ProfileName.TEST).settings)
