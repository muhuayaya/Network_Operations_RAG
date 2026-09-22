"""Trace 阶段、使用量和结构化日志测试。"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta

from netops_copilot.domain.incidents import TraceUsage
from netops_copilot.domain.shared.identity import Principal, SecurityLevel
from netops_copilot.infrastructure.observability import TraceRecorder, structured_trace_json


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        value = self.current
        self.current += timedelta(milliseconds=500)
        return value


class TracingTests(unittest.TestCase):
    def test_slow_stage_is_attributable_and_versions_usage_degradation_are_structured(self) -> None:
        recorder = TraceRecorder(
            clock=_Clock(),
            principal=Principal("p1", SecurityLevel.BASIC, frozenset({"site-sz-hq"})),
            profile="demo-lite",
            versions={"provider": "fake-v1", "index": "idx-v2", "prompt": "p3"},
        )
        recorder.start_stage("lexical-search")
        stage = recorder.end_stage()
        trace = recorder.finish(
            degradation=("reranker:unavailable",),
            usage=TraceUsage(input_tokens=10, output_tokens=5, total_tokens=15, estimated_cost_usd=0.01),
        )

        self.assertEqual(stage.duration_ms, 500.0)
        self.assertEqual(trace.latency_ms, 500.0)
        event = json.loads(structured_trace_json(trace, "query.completed", message="password=secret"))
        self.assertEqual(event["versions"]["index"], "idx-v2")
        self.assertEqual(event["usage"]["total_tokens"], 15)
        self.assertEqual(event["degradation"], ["reranker:unavailable"])
        self.assertEqual(event["message"], "password=[REDACTED]")


if __name__ == "__main__":
    unittest.main()
