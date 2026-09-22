"""demo-lite Profile 使用的 SQLite 元数据仓储。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from netops_copilot.infrastructure.persistence._db_api import (
    DbApiMetadataRepository,
    sqlite_connection,
)


class SqliteMetadataRepository(DbApiMetadataRepository):
    """使用 JSON 载荷和索引别名的 SQLite 元数据存储。"""

    def __init__(
        self,
        database: str | Path | Any = ":memory:",
        *,
        serializer: Callable[[Any], str] | None = None,
        deserializer: Callable[[str], Any] | None = None,
    ) -> None:
        if hasattr(database, "execute"):
            connection = database
            close_connection = False
        else:
            connection = sqlite_connection(database)
            close_connection = True
        super().__init__(
            connection,
            close_connection=close_connection,
            serializer=serializer,
            deserializer=deserializer,
        )
