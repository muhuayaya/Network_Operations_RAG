"""PostgreSQL metadata repository using an injected DB-API connection.

The optional PostgreSQL driver remains an infrastructure deployment concern.  The
adapter accepts an already-open psycopg/psycopg2-style connection so the core
package does not require a database driver for demo-lite or unit tests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from netops_copilot.infrastructure.persistence._db_api import DbApiMetadataRepository


class PostgresMetadataRepository(DbApiMetadataRepository):
    """与 SQLite 遵循相同契约的 PostgreSQL 元数据存储。"""

    def __init__(
        self,
        connection: Any,
        *,
        close_connection: bool = False,
        serializer: Callable[[Any], str] | None = None,
        deserializer: Callable[[str], Any] | None = None,
    ) -> None:
        if not hasattr(connection, "execute"):
            raise TypeError("PostgresMetadataRepository requires an open DB-API connection")
        module_name = type(connection).__module__
        self._placeholder = "?" if module_name.startswith("sqlite3") else "%s"
        super().__init__(
            connection,
            close_connection=close_connection,
            serializer=serializer,
            deserializer=deserializer,
        )
