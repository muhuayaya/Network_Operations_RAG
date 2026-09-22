"""PostgreSQL connection factory used only by the local-milvus runtime."""

from __future__ import annotations

from typing import Any


class PostgresConnectionError(RuntimeError):
    """Raised when the optional PostgreSQL driver or connection is unavailable."""


def connect_postgres(dsn: str, *, connect_timeout: int = 5) -> Any:
    """Open a PostgreSQL DB-API connection without exposing credentials."""

    if not dsn.strip():
        raise PostgresConnectionError("POSTGRES_DSN must not be empty")
    try:
        import psycopg
    except ImportError as error:
        raise PostgresConnectionError(
            "PostgreSQL runtime is unavailable; install the local-milvus extra"
        ) from error
    try:
        return psycopg.connect(dsn, connect_timeout=connect_timeout)
    except psycopg.Error as error:
        raise PostgresConnectionError("PostgreSQL connection failed") from error


def check_postgres(connection: Any) -> tuple[bool, str]:
    """Run a bounded liveness query and return a safe diagnostic."""

    try:
        connection.execute("SELECT 1").fetchone()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as error:
        return False, f"connection failed: {type(error).__name__}"
    return True, "reachable"


__all__ = ["PostgresConnectionError", "check_postgres", "connect_postgres"]
