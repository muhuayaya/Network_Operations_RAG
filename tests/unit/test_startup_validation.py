"""provider、索引和策略快速失败启动校验测试。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from netops_copilot.application.ports import ProviderHealth
from netops_copilot.application.startup import (
    REQUIRED_RUNTIME_CAPABILITIES,
    IndexDescriptor,
    StartupValidationError,
    embedding_fingerprint,
    validate_startup,
)
from netops_copilot.bootstrap import bootstrap, bootstrap_validated
from netops_copilot.settings import ProfileName


class StartupValidationTests(unittest.TestCase):
    """无效 provider、索引和策略会在返回容器前失败。"""

    def setUp(self) -> None:
        self.container = bootstrap(ProfileName.TEST)
        embedding = next(
            provider for provider in self.container.providers if provider.kind.value == "embedding"
        )
        self.index = IndexDescriptor(
            collection_name="test-index",
            schema_version=1,
            embedding_fingerprint=embedding_fingerprint(embedding),
        )

    def test_compatible_profile_bootstraps_after_validation(self) -> None:
        validated = bootstrap_validated(ProfileName.TEST, self.index)

        self.assertEqual(validated.settings.profile, ProfileName.TEST)

    def test_fingerprint_and_schema_mismatches_fail_fast(self) -> None:
        with self.assertRaisesRegex(StartupValidationError, "fingerprint"):
            bootstrap_validated(
                ProfileName.TEST,
                replace(self.index, embedding_fingerprint="unexpected:8:l2:cosine"),
            )
        with self.assertRaisesRegex(StartupValidationError, "schema"):
            bootstrap_validated(ProfileName.TEST, replace(self.index, schema_version=2))

    def test_unavailable_required_provider_and_non_readonly_policy_are_rejected(self) -> None:
        unavailable = tuple(
            replace(provider, health=ProviderHealth.UNAVAILABLE)
            if provider.kind.value == "dense-search"
            else provider
            for provider in self.container.providers
        )
        with self.assertRaisesRegex(StartupValidationError, "dense-search"):
            validate_startup(unavailable, REQUIRED_RUNTIME_CAPABILITIES, self.index, 1, "readonly")
        with self.assertRaisesRegex(StartupValidationError, "readonly"):
            validate_startup(self.container.providers, REQUIRED_RUNTIME_CAPABILITIES, self.index, 1, "write")
