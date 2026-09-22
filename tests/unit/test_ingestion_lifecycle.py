"""失败安全的持久化摄取生命周期测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.indexing import VersionedIndexManager
from netops_copilot.application.ingestion import IngestionCoordinator
from netops_copilot.application.ports.repositories import IndexVersion
from netops_copilot.domain.incidents import INGESTION_STAGES, IngestionStage, IngestionStatus
from netops_copilot.infrastructure.persistence.memory import InMemoryMetadataRepository


class IngestionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMetadataRepository()
        self.manager = VersionedIndexManager(self.repository)
        self.manager.register(IndexVersion("v1", "model-a:8:l2:cosine", 1))
        self.manager.register(IndexVersion("v2", "model-a:8:l2:cosine", 1))
        self.manager.activate("v1")
        self.coordinator = IngestionCoordinator(self.repository, self.manager)

    def test_every_injected_stage_failure_preserves_previous_active_version(self) -> None:
        for index, stage in enumerate(INGESTION_STAGES):
            with self.subTest(stage=stage):
                run = self.coordinator.run(f"job-{index}", "source-1", "v2", fail_at=stage)
                self.assertEqual(run.job.status, IngestionStatus.FAILED)
                self.assertEqual(run.job.stage, stage)
                self.assertEqual(self.manager.active().version.version_id, "v1")

    def test_success_persists_each_stage_and_activates_only_at_end(self) -> None:
        run = self.coordinator.run("job-success", "source-1", "v2")
        self.assertEqual(run.job.status, IngestionStatus.SUCCEEDED)
        self.assertEqual(run.job.stage, IngestionStage.ACTIVATE)
        self.assertEqual(self.repository.get_job("job-success").status, IngestionStatus.SUCCEEDED)
        self.assertEqual(self.manager.active().version.version_id, "v2")
