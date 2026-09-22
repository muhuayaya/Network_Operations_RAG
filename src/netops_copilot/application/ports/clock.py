"""应用时钟契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """向应用服务提供带时区的时刻。"""

    def now(self) -> datetime:
        """返回当前 UTC 时刻。"""
