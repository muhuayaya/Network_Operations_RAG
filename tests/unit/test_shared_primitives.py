"""共享结果、身份、Trace 和时钟基础类型测试。"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID

from netops_copilot.domain.shared import (
    ErrorCode,
    FixedClock,
    Result,
    SecurityLevel,
    ServiceError,
    SystemClock,
    TraceId,
)


class SharedPrimitiveTests(unittest.TestCase):
    """验证可序列化且安全处理 UTC 的基础类型。"""

    def test_result_serializes_a_typed_error_and_trace_id(self) -> None:
        trace_id = TraceId(UUID("12345678-1234-5678-1234-567812345678"))
        result = Result[object].failure(
            ServiceError(ErrorCode.POLICY_DENIED, "access denied"), trace_id
        )

        self.assertEqual(
            result.to_dict(),
            {
                "trace_id": "12345678-1234-5678-1234-567812345678",
                "error": {"code": "POLICY_DENIED", "message": "access denied"},
            },
        )

    def test_clock_values_are_timezone_aware_utc(self) -> None:
        fixed = FixedClock(datetime(2026, 9, 21, 8, 0, tzinfo=UTC))

        self.assertEqual(fixed.now().tzinfo, UTC)
        self.assertEqual(SystemClock().now().tzinfo, UTC)
        with self.assertRaises(ValueError):
            FixedClock(datetime(2026, 9, 21, 8, 0, tzinfo=UTC).replace(tzinfo=None))

    def test_trace_ids_are_uuid_strings(self) -> None:
        self.assertIsInstance(UUID(str(TraceId.new())), UUID)

    def test_basic_principal_cannot_access_restricted_evidence(self) -> None:
        from netops_copilot.domain.shared import Principal

        principal = Principal("basic-demo", SecurityLevel.BASIC, frozenset({"site-gz-dc"}))
        self.assertFalse(principal.can_access("site-gz-dc", SecurityLevel.RESTRICTED))
