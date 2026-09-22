"""安全处理 UTC 的时间和 Trace 基础类型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4


def require_utc(value: datetime) -> datetime:
    """校验并将 datetime 规范化为 UTC 时区。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class TraceId:
    """连接请求、日志和 Trace 的稳定标识。"""

    value: UUID

    @classmethod
    def new(cls) -> TraceId:
        """创建新的请求 Trace 标识。"""
        return cls(uuid4())

    def __str__(self) -> str:
        return str(self.value)


class SystemClock:
    """始终返回带时区 UTC datetime 的生产时钟。"""

    def now(self) -> datetime:
        """返回当前 UTC 时间。"""
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class FixedClock:
    """供测试和场景回放使用的确定性 UTC 时钟。"""

    instant: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "instant", require_utc(self.instant))

    def now(self) -> datetime:
        """返回固定时刻。"""
        return self.instant
