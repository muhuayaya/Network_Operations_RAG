"""安全 doctor 就绪状态测试。"""

from __future__ import annotations

import os
import unittest
from dataclasses import replace

from netops_copilot.application.doctor import DoctorStatus, doctor_report
from netops_copilot.application.ports.providers import ProviderHealth, ProviderKind
from netops_copilot.application.startup import IndexDescriptor, embedding_fingerprint
from netops_copilot.bootstrap import bootstrap, create_builtin_registry
from netops_copilot.settings import ProfileName


class DoctorTests(unittest.TestCase):
    """doctor 能区分必需依赖失败和可选依赖降级。"""

    def setUp(self) -> None:
        self.container = bootstrap(ProfileName.TEST)
        embedding = next(
            provider for provider in self.container.providers if provider.kind is ProviderKind.EMBEDDING
        )
        self.index = IndexDescriptor("test-index", 1, embedding_fingerprint(embedding))

    def test_healthy_profile_with_matching_index(self) -> None:
        report = doctor_report(self.container, self.index)

        self.assertEqual(report.status, DoctorStatus.HEALTHY)

    def test_optional_unavailable_provider_is_optional_degraded(self) -> None:
        registry = create_builtin_registry()
        optional = registry.create(ProviderKind.RERANKER, "local-reserved", self.container.settings)
        report = doctor_report(self.container, self.index, (replace(optional, health=ProviderHealth.UNAVAILABLE),))

        self.assertEqual(report.status, DoctorStatus.OPTIONAL_DEGRADED)

    def test_missing_index_is_required_unavailable(self) -> None:
        report = doctor_report(self.container)

        self.assertEqual(report.status, DoctorStatus.REQUIRED_UNAVAILABLE)

    def test_missing_cloud_secret_only_reports_variable_name(self) -> None:
        os.environ.pop("DASHSCOPE_API_KEY", None)
        cloud = bootstrap(ProfileName.DEMO_LITE)

        report = doctor_report(cloud)
        serialized = str(report.to_dict())

        self.assertEqual(report.status, DoctorStatus.REQUIRED_UNAVAILABLE)
        self.assertIn("DASHSCOPE_API_KEY", serialized)
        self.assertNotIn("secret-value", serialized)
