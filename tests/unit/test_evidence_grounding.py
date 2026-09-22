"""证据边界、引用校验和无证据拒答测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.evidence import (
    AnswerSentence,
    EvidenceAssembler,
    EvidenceLimits,
    EvidenceValidationError,
    ground_answer,
)
from netops_copilot.domain.inventory import DataSecurityLevel
from netops_copilot.domain.knowledge import Citation, KnowledgeChunk


class EvidenceGroundingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunk = KnowledgeChunk(
            "chunk-1",
            "source-1",
            "v1",
            "OSPF neighbor is in ExStart.",
            "manual.md#p1",
            "hash",
            DataSecurityLevel.INTERNAL,
            {"site_id": "site-gz-dc"},
        )
        self.citation = Citation("chunk-1", "source-1", "manual.md#p1")

    def test_assembler_bounds_chunks_and_grounded_sentence(self) -> None:
        bundle = EvidenceAssembler(EvidenceLimits(max_chunks=1, max_chars=100)).assemble(
            [self.chunk, self.chunk], [self.citation]
        )
        answer = ground_answer(bundle, [AnswerSentence("Neighbor is in ExStart.", (self.citation,))])
        self.assertFalse(answer.refused)
        self.assertEqual(len(bundle.chunks), 1)

    def test_no_evidence_refuses_and_uncited_facts_fail(self) -> None:
        empty = EvidenceAssembler().assemble([], [])
        self.assertEqual(ground_answer(empty, [AnswerSentence("No facts.")]).refusal_code, "no_evidence")
        bundle = EvidenceAssembler().assemble([self.chunk], [self.citation])
        with self.assertRaises(EvidenceValidationError):
            ground_answer(bundle, [AnswerSentence("Uncited fact.")])
        inferred = ground_answer(bundle, [AnswerSentence("This may indicate a protocol issue.", inference=True)])
        self.assertFalse(inferred.refused)
