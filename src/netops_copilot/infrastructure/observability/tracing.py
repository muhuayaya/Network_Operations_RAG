"""Trace 记录和结构化事件渲染。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from netops_copilot.application.ports.clock import Clock
from netops_copilot.domain.incidents import QueryTrace, TraceStage, TraceUsage
from netops_copilot.domain.shared.identity import Principal
from netops_copilot.domain.shared.time import TraceId, require_utc
from netops_copilot.infrastructure.observability.redaction import redact_log_message


@dataclass(frozen=True, slots=True)
class _OpenStage:
    name: str
    started_at: datetime


class TraceRecorder:
    """记录阶段跨度，但不让应用代码依赖遥测 SDK。"""

    def __init__(
        self,
        *,
        clock: Clock,
        principal: Principal,
        profile: str,
        versions: dict[str, str],
        trace_id: TraceId | None = None,
        trace_type: str = "query",
    ) -> None:
        self._clock = clock
        self._principal = principal
        self._profile = profile
        self._versions = dict(versions)
        self._trace_id = trace_id or TraceId.new()
        self._trace_type = trace_type
        self._stages: list[TraceStage] = []
        self._open: _OpenStage | None = None

    @property
    def trace_id(self) -> TraceId:
        return self._trace_id

    def start_stage(self, name: str) -> None:
        if self._open is not None:
            raise ValueError("a trace stage is already open")
        self._open = _OpenStage(name, require_utc(self._clock.now()))

    def end_stage(self) -> TraceStage:
        if self._open is None:
            raise ValueError("no trace stage is open")
        ended_at = require_utc(self._clock.now())
        stage = TraceStage(self._open.name, self._open.started_at, ended_at)
        self._stages.append(stage)
        self._open = None
        return stage

    def finish(
        self,
        *,
        degradation: tuple[str, ...] = (),
        usage: TraceUsage | None = None,
    ) -> QueryTrace:
        if self._open is not None:
            raise ValueError("cannot finish a trace with an open stage")
        return QueryTrace(
            trace_id=self._trace_id,
            principal=self._principal,
            profile=self._profile,
            created_at=require_utc(self._clock.now()),
            stages=tuple(self._stages),
            versions=self._versions,
            degradation=degradation,
            usage=usage,
            trace_type=self._trace_type,
        )


def structured_trace_event(trace: QueryTrace, event: str, **fields: Any) -> dict[str, Any]:
    """渲染与 Trace 关联且不泄露秘密的结构化日志事件。"""
    message = redact_log_message(str(fields.pop("message", "")))
    return {
        "event": event,
        "trace_id": str(trace.trace_id),
        "profile": trace.profile,
        "trace_type": trace.trace_type,
        "versions": dict(trace.versions),
        "degradation": list(trace.degradation),
        "latency_ms": trace.latency_ms,
        "usage": _usage_mapping(trace.usage),
        "message": message,
        **fields,
    }


def structured_trace_json(trace: QueryTrace, event: str, **fields: Any) -> str:
    """将一个结构化事件序列化为一行 JSON 日志。"""
    return json.dumps(structured_trace_event(trace, event, **fields), ensure_ascii=False, sort_keys=True)


def _usage_mapping(usage: TraceUsage | None) -> dict[str, Any] | None:
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "estimated_cost_usd": usage.estimated_cost_usd,
    }
