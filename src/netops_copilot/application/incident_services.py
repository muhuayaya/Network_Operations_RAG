"""确定性优先的事故和配置解释服务。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from netops_copilot.application.config_diff import ConfigurationDiff, diff_configurations
from netops_copilot.application.correlation import AlarmCorrelator, CorrelationMatch, IncidentSignal
from netops_copilot.application.ports.models import LLMPort, LLMRequest, LLMResult, ModelStatus
from netops_copilot.application.safety import delimit_evidence
from netops_copilot.domain.configurations import ConfigChange
from netops_copilot.domain.incidents import EvidenceBundle
from netops_copilot.domain.inventory import Vendor
from netops_copilot.domain.knowledge import Citation, KnowledgeChunk
from netops_copilot.domain.observations import AlarmEvent


class KnowledgeRetriever(Protocol):
    """应用层自有的最小检索契约，用于分析后的证据获取。"""

    def retrieve(self, query: str, limit: int = 8) -> Sequence[KnowledgeChunk]:
        """为解释查询返回已授权的知识分块。"""


@dataclass(frozen=True, slots=True)
class IncidentDiagnosis:
    """告警调查事实和可选的模型解释。"""

    primary: IncidentSignal
    correlations: tuple[CorrelationMatch, ...]
    evidence: EvidenceBundle
    facts: tuple[str, ...]
    explanation: str | None = None
    model_status: ModelStatus | None = None


@dataclass(frozen=True, slots=True)
class ConfigurationExplanation:
    """确定性差异、检索证据和可选解释。"""

    diff: ConfigurationDiff
    evidence: EvidenceBundle
    facts: tuple[str, ...]
    explanation: str | None = None
    model_status: ModelStatus | None = None


class DiagnoseAlarmIncident:
    """先关联告警事实，再检索知识或调用 LLM。"""

    def __init__(
        self,
        retriever: KnowledgeRetriever,
        llm: LLMPort | None = None,
        correlator: AlarmCorrelator | None = None,
        *,
        evidence_limit: int = 8,
    ) -> None:
        if evidence_limit < 1:
            raise ValueError("evidence_limit must be positive")
        self._retriever = retriever
        self._llm = llm
        self._correlator = correlator or AlarmCorrelator()
        self._evidence_limit = evidence_limit

    def diagnose(
        self,
        primary: IncidentSignal | AlarmEvent,
        candidates: Iterable[IncidentSignal | AlarmEvent] = (),
    ) -> IncidentDiagnosis:
        primary_signal = _signal(primary)
        candidate_signals = tuple(_signal(candidate) for candidate in candidates)
        correlations = self._correlator.correlate(primary_signal, candidate_signals)
        facts = _incident_facts(primary_signal, correlations)
        query = " ".join(facts)
        chunks = tuple(self._retriever.retrieve(query, limit=self._evidence_limit))
        evidence = EvidenceBundle(
            alarms=(primary,) if isinstance(primary, AlarmEvent) else (),
            chunks=chunks,
            citations=_citations(chunks),
        )
        explanation, status = _explain(self._llm, _incident_prompt(facts, chunks))
        return IncidentDiagnosis(primary_signal, correlations, evidence, facts, explanation, status)


class ExplainConfigurationDiff:
    """先计算差异，再检索知识或请求模型解释。"""

    def __init__(self, retriever: KnowledgeRetriever, llm: LLMPort | None = None, *, evidence_limit: int = 8) -> None:
        if evidence_limit < 1:
            raise ValueError("evidence_limit must be positive")
        self._retriever = retriever
        self._llm = llm
        self._evidence_limit = evidence_limit

    def explain(
        self,
        diff_or_baseline: ConfigurationDiff | str,
        current: str | None = None,
        *,
        vendor: Vendor | str | None = None,
    ) -> ConfigurationExplanation:
        if isinstance(diff_or_baseline, ConfigurationDiff):
            if current is not None or vendor is not None:
                raise ValueError("vendor/current are only valid when raw snapshots are supplied")
            diff = diff_or_baseline
        else:
            if current is None:
                raise ValueError("current snapshot is required")
            diff = diff_configurations(diff_or_baseline, current, vendor=vendor)
        facts = _diff_facts(diff.changes)
        query = " ".join(facts) or "configuration diff no changes"
        chunks = tuple(self._retriever.retrieve(query, limit=self._evidence_limit))
        evidence = EvidenceBundle(chunks=chunks, citations=_citations(chunks), diffs=diff.changes)
        explanation, status = _explain(self._llm, _diff_prompt(facts, chunks))
        return ConfigurationExplanation(diff, evidence, facts, explanation, status)


def _signal(value: IncidentSignal | AlarmEvent) -> IncidentSignal:
    if isinstance(value, IncidentSignal):
        return value
    return IncidentSignal(
        incident_id=value.alarm_id,
        device_id=str(value.device_id),
        occurred_at=value.raised_at,
        interface=str(value.interface) if value.interface is not None else None,
        text=value.summary,
    )


def _incident_facts(primary: IncidentSignal, correlations: Sequence[CorrelationMatch]) -> tuple[str, ...]:
    facts = [
        f"primary incident={primary.incident_id} device={primary.device_id} occurred_at={primary.occurred_at.isoformat()}",
    ]
    if primary.interface:
        facts.append(f"primary interface={primary.interface}")
    if primary.protocol_state:
        facts.append(f"primary protocol_state={primary.protocol_state}")
    facts.extend(
        f"correlated incident={match.incident_id} score={match.score} reasons={','.join(match.reasons)}"
        for match in correlations
    )
    return tuple(facts)


def _diff_facts(changes: Sequence[ConfigChange]) -> tuple[str, ...]:
    return tuple(
        "change "
        f"section={change.section} path={change.path} operation={change.operation.value} "
        f"before={change.before!r} after={change.after!r} risk={change.risk_level.value}"
        for change in changes
    )


def _citations(chunks: Sequence[KnowledgeChunk]) -> tuple[Citation, ...]:
    return tuple(Citation(chunk.chunk_id, chunk.source_id, chunk.source_locator) for chunk in chunks)


def _incident_prompt(facts: Sequence[str], chunks: Sequence[KnowledgeChunk]) -> str:
    return "Deterministic incident facts:\n" + "\n".join(facts) + "\nEvidence:\n" + delimit_evidence(chunks).text


def _diff_prompt(facts: Sequence[str], chunks: Sequence[KnowledgeChunk]) -> str:
    return "Deterministic configuration diff facts:\n" + ("\n".join(facts) or "no changes") + "\nEvidence:\n" + delimit_evidence(chunks).text


def _explain(llm: LLMPort | None, prompt: str) -> tuple[str | None, ModelStatus | None]:
    if llm is None:
        return None, None
    result: LLMResult = llm.complete(
        LLMRequest(
            prompt=prompt,
            system=(
                "Explain the supplied deterministic facts only. Do not add, remove, or rewrite "
                "facts, source identifiers, line references, operations, or risk levels."
            ),
        )
    )
    if result.status is not ModelStatus.SUCCESS:
        return None, result.status
    return result.text, result.status
