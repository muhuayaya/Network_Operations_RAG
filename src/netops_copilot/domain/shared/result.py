"""所有交付接口统一的成功和失败结果。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from netops_copilot.domain.shared.time import TraceId

T = TypeVar("T")


class ErrorCode(StrEnum):
    """REST、MCP、CLI 和 Streamlit 适配器共享的稳定错误码。"""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    FORBIDDEN = "FORBIDDEN"
    NO_EVIDENCE = "NO_EVIDENCE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    DEGRADED_RESULT = "DEGRADED_RESULT"
    INDEX_VERSION_MISMATCH = "INDEX_VERSION_MISMATCH"
    INGESTION_FAILED = "INGESTION_FAILED"
    POLICY_DENIED = "POLICY_DENIED"


@dataclass(frozen=True, slots=True)
class ServiceError:
    """安全且可序列化的失败描述。"""

    code: ErrorCode
    message: str

    def to_dict(self) -> dict[str, str]:
        """只序列化公开错误信息。"""
        return {"code": self.code.value, "message": self.message}


@dataclass(frozen=True, slots=True)
class Result(Generic[T]):
    """一个用例结果只能包含值或类型化错误，不能同时包含两者。"""

    trace_id: TraceId
    value: T | None = None
    error: ServiceError | None = None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.error is None):
            raise ValueError("Result requires exactly one of value or error")

    @classmethod
    def success(cls, value: T, trace_id: TraceId) -> Result[T]:
        """创建成功结果。"""
        return cls(trace_id=trace_id, value=value)

    @classmethod
    def failure(cls, error: ServiceError, trace_id: TraceId) -> Result[T]:
        """创建失败结果。"""
        return cls(trace_id=trace_id, error=error)

    @property
    def is_success(self) -> bool:
        """判断结果是否包含值。"""
        return self.error is None

    def to_dict(self) -> dict[str, object]:
        """序列化结果封装，不假定成功值的具体结构。"""
        payload: dict[str, object] = {"trace_id": str(self.trace_id)}
        if self.error is not None:
            payload["error"] = self.error.to_dict()
        else:
            payload["value"] = self.value
        return payload
