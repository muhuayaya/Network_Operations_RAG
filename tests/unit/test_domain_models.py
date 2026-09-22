"""观测、配置、知识和生命周期模型测试。"""

from __future__ import annotations

import unittest

from netops_copilot.domain.configurations import ChangeOperation, ConfigChange, RiskLevel
from netops_copilot.domain.incidents import (
    EvidenceBundle,
    IngestionJob,
    IngestionStage,
    IngestionStatus,
)
from netops_copilot.domain.inventory import DataSecurityLevel
from netops_copilot.domain.knowledge import Citation, KnowledgeChunk


class DomainModelTests(unittest.TestCase):
    """验证来源溯源和显式状态转换。"""

    def test_evidence_requires_citation_for_each_chunk(self) -> None:
        chunk = KnowledgeChunk(
            "chunk-1",
            "source-1",
            "v1",
            "OSPF read-only verification",
            "manual.md#ospf",
            "hash-1",
            DataSecurityLevel.INTERNAL,
            {"vendor": "Huawei"},
        )
        with self.assertRaises(ValueError):
            EvidenceBundle(chunks=(chunk,))
        bundle = EvidenceBundle(
            chunks=(chunk,),
            citations=(Citation("chunk-1", "source-1", "manual.md#ospf"),),
        )
        self.assertEqual(bundle.citations[0].chunk_id, "chunk-1")

    def test_ingestion_state_machine_preserves_failure_and_retry_stage(self) -> None:
        job = IngestionJob("job-1", "source-1").start()
        failed = job.fail("EMBEDDING_UNAVAILABLE")
        retried = failed.retry()
        next_stage = retried.start().succeed()

        self.assertEqual(failed.status, IngestionStatus.FAILED)
        self.assertEqual(retried.stage, IngestionStage.DISCOVER)
        self.assertEqual(next_stage.stage, IngestionStage.VALIDATE)
        self.assertEqual(next_stage.status, IngestionStatus.PENDING)

    def test_configuration_change_validates_operation_and_line_provenance(self) -> None:
        change = ConfigChange(
            "acl",
            "acl/3000/rule-10",
            ChangeOperation.MODIFY,
            "permit ip any any",
            "deny ip any any",
            (10, 11),
            ("traffic-impact",),
            RiskLevel.HIGH,
        )
        self.assertEqual(change.risk_level, RiskLevel.HIGH)
        with self.assertRaises(ValueError):
            ConfigChange("acl", "acl/1", ChangeOperation.ADD, None, None, (0,), ())
