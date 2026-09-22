"""REST 和 MCP 测试使用的与传输无关的语义响应投影。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SemanticResponse:
    """跨传输时必须保持含义一致的字段。"""

    data: Any = None
    evidence_ids: tuple[str, ...] = ()
    error_code: str | None = None
    degradation: tuple[str, ...] = ()
    trace_id: str = ""

    def as_mapping(self) -> dict[str, Any]:
        return {
            "data": self.data,
            "evidence_ids": self.evidence_ids,
            "error_code": self.error_code,
            "degradation": self.degradation,
            "trace_id": self.trace_id,
        }


def semantic_projection(value: Mapping[str, Any] | SemanticResponse) -> SemanticResponse:
    """规范化 REST/MCP 载荷，供语义一致性断言使用。"""
    if isinstance(value, SemanticResponse):
        return value
    error = value.get("error")
    error_code = value.get("error_code")
    if error_code is None and isinstance(error, Mapping):
        error_code = error.get("code")
    evidence = value.get("evidence_ids", ())
    degradation = value.get("degradation", ())
    return SemanticResponse(
        data=value.get("data", value),
        evidence_ids=tuple(str(item) for item in evidence),
        error_code=str(error_code) if error_code is not None else None,
        degradation=tuple(str(item) for item in degradation),
        trace_id=str(value.get("trace_id", "")),
    )


__all__ = ["SemanticResponse", "semantic_projection"]
