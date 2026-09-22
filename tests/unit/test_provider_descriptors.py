"""provider 能力和兼容性校验测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.ports import (
    Capability,
    DistanceMetric,
    EmbeddingNormalization,
    ProviderCompatibilityError,
    ProviderDescriptor,
    ProviderHealth,
    ProviderKind,
    validate_provider_compatibility,
)


def descriptor(kind: ProviderKind, **overrides: object) -> ProviderDescriptor:
    """构建适用于兼容性测试的就绪描述符。"""
    capability = Capability(kind.value)
    defaults: dict[str, object] = {
        "name": f"fake-{kind.value}",
        "kind": kind,
        "version": "1",
        "capabilities": frozenset({capability}),
        "health": ProviderHealth.READY,
    }
    if kind is ProviderKind.EMBEDDING:
        defaults.update(
            {
                "embedding_dimension": 8,
                "normalization": EmbeddingNormalization.L2,
                "distance_metric": DistanceMetric.COSINE,
            }
        )
    defaults.update(overrides)
    return ProviderDescriptor(**defaults)  # type: ignore[arg-type]  # 测试辅助构造器允许动态字段。


class ProviderDescriptorTests(unittest.TestCase):
    """能力声明只暴露兼容的 provider 组合。"""

    def test_complete_provider_set_is_compatible(self) -> None:
        providers = [descriptor(kind) for kind in ProviderKind]

        validate_provider_compatibility(providers, frozenset(Capability))

    def test_missing_or_unavailable_capability_is_rejected(self) -> None:
        providers = [
            descriptor(ProviderKind.LLM),
            descriptor(ProviderKind.DENSE_SEARCH, health=ProviderHealth.UNAVAILABLE),
        ]

        with self.assertRaisesRegex(ProviderCompatibilityError, "dense-search"):
            validate_provider_compatibility(providers, frozenset({Capability.DENSE_SEARCH}))

    def test_descriptor_rejects_incompatible_embedding_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "embedding providers require a positive dimension"):
            descriptor(ProviderKind.EMBEDDING, embedding_dimension=None)

        with self.assertRaisesRegex(ValueError, "only valid for embedding providers"):
            descriptor(ProviderKind.LLM, embedding_dimension=8)

    def test_duplicate_provider_names_are_rejected(self) -> None:
        providers = [
            descriptor(ProviderKind.LLM, name="duplicate"),
            descriptor(ProviderKind.EMBEDDING, name="duplicate"),
        ]

        with self.assertRaisesRegex(ProviderCompatibilityError, "unique"):
            validate_provider_compatibility(providers, frozenset())
