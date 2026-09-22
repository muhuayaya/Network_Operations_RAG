"""确定性优先服务测试。"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from netops_copilot.application import (
    DiagnoseAlarmIncident,
    ExplainConfigurationDiff,
    IncidentSignal,
)
from netops_copilot.application.ports.models import LLMRequest, LLMResult, ModelStatus
from netops_copilot.domain.inventory import DataSecurityLevel, Vendor
from netops_copilot.domain.knowledge import KnowledgeChunk


class _Retriever:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, query: str, limit: int = 8) -> tuple[KnowledgeChunk, ...]:
        self.queries.append(query)
        return (
            KnowledgeChunk(
                chunk_id="chunk-1",
                source_id="source-1",
                version="v1",
                text="Check MTU and OSPF neighbor state.",
                source_locator="knowledge.md#1",
                content_hash="hash-1",
                security_level=DataSecurityLevel.INTERNAL,
                metadata={},
            ),
        )[:limit]


class _MaliciousLLM:
    def complete(self, request: LLMRequest, timeout_seconds: float = 30.0) -> LLMResult:
        del request, timeout_seconds
        return LLMResult(ModelStatus.SUCCESS, "The deterministic risk is low and the incident id is replaced.")


class IncidentServiceTests(unittest.TestCase):
    def test_diagnosis_correlates_before_retrieval_and_keeps_facts_outside_model_text(self) -> None:
        retriever = _Retriever()
        primary = IncidentSignal(
            incident_id="inc-1",
            device_id="hw-01",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            interface="ethernet1/0/1",
            protocol_state="ExStart",
            text="OSPF MTU mismatch",
        )
        candidate = IncidentSignal(
            incident_id="inc-2",
            device_id="hw-01",
            occurred_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            interface="ethernet1/0/1",
            protocol_state="ExStart",
            text="OSPF MTU mismatch",
        )

        result = DiagnoseAlarmIncident(retriever, _MaliciousLLM()).diagnose(primary, [candidate])

        self.assertEqual(result.primary.incident_id, "inc-1")
        self.assertEqual(result.correlations[0].incident_id, "inc-2")
        self.assertIn("primary incident=inc-1", result.facts[0])
        self.assertEqual(result.evidence.citations[0].chunk_id, "chunk-1")
        self.assertIn("inc-1", retriever.queries[0])
        self.assertIn("replaced", result.explanation or "")

    def test_configuration_explanation_retrieves_after_diff_and_preserves_risk_facts(self) -> None:
        retriever = _Retriever()
        baseline = "acl number 3001\n rule 10 permit ip\n"
        current = "acl number 3001\n rule 10 deny ip\n"

        result = ExplainConfigurationDiff(retriever, _MaliciousLLM()).explain(
            baseline,
            current,
            vendor=Vendor.HUAWEI,
        )

        self.assertEqual(len(result.diff.changes), 1)
        self.assertEqual(result.diff.changes[0].risk_level.value, "high")
        self.assertIn("risk=high", result.facts[0])
        self.assertIn("section=acl", retriever.queries[0])
        self.assertEqual(result.evidence.diffs, result.diff.changes)
        self.assertEqual(result.model_status, ModelStatus.SUCCESS)


if __name__ == "__main__":
    unittest.main()
