"""共享且独立于框架的领域基础类型。"""

from netops_copilot.domain.shared.identity import Principal, SecurityLevel
from netops_copilot.domain.shared.result import ErrorCode, Result, ServiceError
from netops_copilot.domain.shared.time import FixedClock, SystemClock, TraceId, require_utc

__all__ = [
    "ErrorCode",
    "FixedClock",
    "Principal",
    "Result",
    "SecurityLevel",
    "ServiceError",
    "SystemClock",
    "TraceId",
    "require_utc",
]
