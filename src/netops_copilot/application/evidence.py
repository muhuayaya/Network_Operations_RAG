"""有边界的证据组装和基于引用的答案校验。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from netops_copilot.domain.incidents import EvidenceBundle
from netops_copilot.domain.knowledge import Citation, KnowledgeChunk


class EvidenceValidationError(ValueError):
    """答案句子无法关联到已授权证据时抛出的异常。"""


@dataclass(frozen=True, slots=True)
class EvidenceLimits:
    max_chunks: int = 8
    max_chars: int = 8_000

    def __post_init__(self) -> None:
        if self.max_chunks < 1 or self.max_chars < 1:
            raise ValueError("evidence limits must be positive")


class EvidenceAssembler:
    """在不改变来源事实的前提下构建有边界的证据包。"""

    def __init__(self, limits: EvidenceLimits | None = None) -> None:
        self._limits = limits or EvidenceLimits()

    def assemble(
        self,
        chunks: Sequence[KnowledgeChunk],
        citations: Sequence[Citation],
    ) -> EvidenceBundle:
        bounded: list[KnowledgeChunk] = []
        used_chars = 0
        for chunk in chunks:
            if len(bounded) >= self._limits.max_chunks or used_chars + len(chunk.text) > self._limits.max_chars:
                break
            bounded.append(chunk)
            used_chars += len(chunk.text)
        allowed_ids = {chunk.chunk_id for chunk in bounded}
        bounded_citations = tuple(citation for citation in citations if citation.chunk_id in allowed_ids)
        return EvidenceBundle(chunks=tuple(bounded), citations=bounded_citations)


@dataclass(frozen=True, slots=True)
class AnswerSentence:
    """包含必需引用或明确推断标记的一个答案句子。"""

    text: str
    citations: tuple[Citation, ...] = ()
    inference: bool = False

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("answer sentence cannot be blank")


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    """结构化答案，或明确说明没有证据的拒答。"""

    sentences: tuple[AnswerSentence, ...] = ()
    refusal_code: str | None = None

    @property
    def refused(self) -> bool:
        return self.refusal_code is not None


def ground_answer(evidence: EvidenceBundle, sentences: Sequence[AnswerSentence]) -> GroundedAnswer:
    """返回事实性答案句子前先校验引用。"""
    if not evidence.chunks:
        return GroundedAnswer(refusal_code="no_evidence")
    allowed = {(citation.chunk_id, citation.source_id, citation.source_locator) for citation in evidence.citations}
    for sentence in sentences:
        if sentence.inference:
            continue
        if not sentence.citations:
            raise EvidenceValidationError("factual answer sentence requires a citation")
        for citation in sentence.citations:
            if (citation.chunk_id, citation.source_id, citation.source_locator) not in allowed:
                raise EvidenceValidationError("answer citation is not present in the evidence bundle")
    return GroundedAnswer(tuple(sentences))
