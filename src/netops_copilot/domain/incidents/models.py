"""事故、证据和生命周期 Trace 模型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from netops_copilot.domain.configurations import ConfigChange
from netops_copilot.domain.inventory import DeviceId, SiteId
from netops_copilot.domain.knowledge import Citation, KnowledgeChunk
from netops_copilot.domain.observations import AlarmEvent
from netops_copilot.domain.shared.identity import Principal
from netops_copilot.domain.shared.time import TraceId, require_utc


@dataclass(frozen=True, slots=True)
class IncidentTicket:
    """合成或脱敏的历史工单。"""

    ticket_id: str
    scenario_id: str
    site_id: SiteId
    device_id: DeviceId
    symptoms: str
    cause: str
    actions: tuple[str, ...]
    outcome: str
    opened_at: datetime
    status: str
    synthetic: bool = True

    def __post_init__(self) -> None:
        if not self.ticket_id.strip() or not self.scenario_id.strip():
            raise ValueError("ticket and scenario identifiers cannot be empty")
        if not self.symptoms.strip() or not self.cause.strip() or not self.outcome.strip():
            raise ValueError("ticket facts cannot be empty")
        if not self.actions:
            raise ValueError("ticket must retain its action history")
        object.__setattr__(self, "opened_at", require_utc(self.opened_at))


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """传给模型进行解释的确定性事实和引用。"""

    alarms: tuple[AlarmEvent, ...] = ()
    chunks: tuple[KnowledgeChunk, ...] = ()
    tickets: tuple[IncidentTicket, ...] = ()
    diffs: tuple[ConfigChange, ...] = ()
    citations: tuple[Citation, ...] = ()

    def __post_init__(self) -> None:
        chunk_ids = {chunk.chunk_id for chunk in self.chunks}
        cited_chunk_ids = {citation.chunk_id for citation in self.citations}
        if not chunk_ids.issubset(cited_chunk_ids):
            raise ValueError("every evidence chunk must have a citation")


class IngestionStage(StrEnum):
    """已持久化的摄取阶段。"""

    DISCOVER = "discover"
    VALIDATE = "validate"
    REDACT = "redact"
    PARSE = "parse"
    NORMALIZE = "normalize"
    CHUNK = "chunk"
    ENRICH_RULES = "enrich_rules"
    EMBED = "embed"
    INDEX = "index"
    VERIFY = "verify"
    ACTIVATE = "activate"


class IngestionStatus(StrEnum):
    """摄取任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


INGESTION_STAGES = tuple(IngestionStage)


@dataclass(frozen=True, slots=True)
class IngestionJob:
    """一个来源摄取任务的不可变状态机快照。"""

    job_id: str
    source_id: str
    stage: IngestionStage = IngestionStage.DISCOVER
    status: IngestionStatus = IngestionStatus.PENDING
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.job_id.strip() or not self.source_id.strip():
            raise ValueError("ingestion job and source identifiers cannot be empty")
        if self.status is IngestionStatus.FAILED and not self.error_code:
            raise ValueError("failed ingestion jobs require an error code")
        if self.status is not IngestionStatus.FAILED and self.error_code is not None:
            raise ValueError("only failed ingestion jobs may carry an error code")

    def start(self) -> IngestionJob:
        """将当前阶段标记为运行中。"""
        if self.status is not IngestionStatus.PENDING:
            raise ValueError("only pending ingestion stages can start")
        return replace(self, status=IngestionStatus.RUNNING)

    def succeed(self) -> IngestionJob:
        """完成当前阶段并推进，或激活终止阶段。"""
        if self.status is not IngestionStatus.RUNNING:
            raise ValueError("only running ingestion stages can succeed")
        stage_index = INGESTION_STAGES.index(self.stage)
        if stage_index == len(INGESTION_STAGES) - 1:
            return replace(self, status=IngestionStatus.SUCCEEDED)
        return replace(self, stage=INGESTION_STAGES[stage_index + 1], status=IngestionStatus.PENDING)

    def fail(self, error_code: str) -> IngestionJob:
        """持久化阶段失败，但不改变之前的活动版本。"""
        if self.status is not IngestionStatus.RUNNING:
            raise ValueError("only running ingestion stages can fail")
        return replace(self, status=IngestionStatus.FAILED, error_code=error_code)

    def retry(self) -> IngestionJob:
        """将失败任务返回到原阶段，以便安全重试。"""
        if self.status is not IngestionStatus.FAILED:
            raise ValueError("only failed ingestion stages can retry")
        return replace(self, status=IngestionStatus.PENDING, error_code=None)


@dataclass(frozen=True, slots=True)
class TraceStage:
    """查询或摄取 Trace 中的一个计量阶段。"""

    name: str
    started_at: datetime
    ended_at: datetime

    def __post_init__(self) -> None:
        started_at = require_utc(self.started_at)
        ended_at = require_utc(self.ended_at)
        if not self.name.strip() or ended_at < started_at:
            raise ValueError("trace stage has invalid name or time interval")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "ended_at", ended_at)

    @property
    def duration_ms(self) -> float:
        """返回经过的毫秒数。"""
        return (self.ended_at - self.started_at).total_seconds() * 1000


@dataclass(frozen=True, slots=True)
class TraceUsage:
    """附加到 Trace 的 provider token 和成本统计。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.total_tokens) < 0:
            raise ValueError("trace usage token counts cannot be negative")
        if self.estimated_cost_usd is not None and self.estimated_cost_usd < 0:
            raise ValueError("trace usage cost cannot be negative")


@dataclass(frozen=True, slots=True)
class QueryTrace:
    """记录 Profile、身份、阶段和降级信息的审计 Trace。"""

    trace_id: TraceId
    principal: Principal
    profile: str
    created_at: datetime
    stages: tuple[TraceStage, ...]
    versions: Mapping[str, str]
    degradation: tuple[str, ...] = ()
    usage: TraceUsage | None = None
    trace_type: str = "query"

    def __post_init__(self) -> None:
        if not self.profile.strip():
            raise ValueError("trace profile cannot be empty")
        object.__setattr__(self, "created_at", require_utc(self.created_at))
        object.__setattr__(self, "versions", MappingProxyType(dict(self.versions)))
        if not self.trace_type.strip():
            raise ValueError("trace type cannot be empty")

    @property
    def latency_ms(self) -> float:
        """返回记录阶段覆盖的端到端时长。"""
        if not self.stages:
            return 0.0
        return (max(stage.ended_at for stage in self.stages) - min(stage.started_at for stage in self.stages)).total_seconds() * 1000
