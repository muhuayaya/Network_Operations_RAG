"""SQLite 和 PostgreSQL 元数据存储共享的 DB-API 实现。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from netops_copilot.application.ports.repositories import (
    IndexVersion,
    IndexVersionStatus,
    RepositoryNotFoundError,
)


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(cast(Any, value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"metadata record is not JSON serializable: {type(value).__name__}")


class DbApiMetadataRepository:
    """使用小型 DB-API 兼容接口的可移植元数据仓储。"""

    _placeholder = "?"

    def __init__(
        self,
        connection: Any,
        *,
        close_connection: bool = False,
        serializer: Callable[[Any], str] | None = None,
        deserializer: Callable[[str], Any] | None = None,
    ) -> None:
        self._connection = connection
        self._close_connection = close_connection
        self._serialize = serializer or (lambda value: json.dumps(value, default=_json_default))
        self._deserialize = deserializer or json.loads
        self._create_schema()

    def close(self) -> None:
        if self._close_connection:
            self._connection.close()

    def _execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> Any:
        cursor = self._connection.execute(statement, parameters)
        self._connection.commit()
        return cursor

    def _fetchone(self, statement: str, parameters: tuple[Any, ...] = ()) -> Any:
        cursor = self._connection.execute(statement, parameters)
        return cursor.fetchone()

    def _create_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata_records (
                collection TEXT NOT NULL,
                record_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (collection, record_id)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS index_versions (
                version_id TEXT PRIMARY KEY,
                embedding_fingerprint TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS index_aliases (
                alias TEXT PRIMARY KEY,
                version_id TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def _save_record(self, collection: str, record_id: str, record: Any) -> None:
        if not record_id.strip():
            raise ValueError("metadata record id cannot be empty")
        statement = (
            "INSERT INTO metadata_records(collection, record_id, payload) "
            f"VALUES ({self._placeholder}, {self._placeholder}, {self._placeholder}) "
            "ON CONFLICT(collection, record_id) DO UPDATE SET payload=excluded.payload"
        )
        self._execute(statement, (collection, record_id, self._serialize(record)))

    def _get_record(self, collection: str, record_id: str) -> Any:
        row = self._fetchone(
            f"SELECT payload FROM metadata_records WHERE collection={self._placeholder} "
            f"AND record_id={self._placeholder}",
            (collection, record_id),
        )
        if row is None:
            raise RepositoryNotFoundError(record_id)
        return self._deserialize(row[0])

    def save_inventory(self, entity_id: str, entity: Any) -> None:
        self._save_record("inventory", entity_id, entity)

    def get_inventory(self, entity_id: str) -> Any:
        return self._get_record("inventory", entity_id)

    def save_source(self, source_id: str, source: Any) -> None:
        self._save_record("source", source_id, source)

    def get_source(self, source_id: str) -> Any:
        return self._get_record("source", source_id)

    def save_job(self, job_id: str, job: Any) -> None:
        self._save_record("job", job_id, job)

    def get_job(self, job_id: str) -> Any:
        return self._get_record("job", job_id)

    def save_trace(self, trace_id: str, trace: Any) -> None:
        self._save_record("trace", trace_id, trace)

    def get_trace(self, trace_id: str) -> Any:
        return self._get_record("trace", trace_id)

    def save_index_version(self, version: IndexVersion) -> None:
        if self._fetchone(
            f"SELECT version_id FROM index_versions WHERE version_id={self._placeholder}",
            (version.version_id,),
        ) is not None:
            raise ValueError(f"index version already exists: {version.version_id}")
        self._execute(
            "INSERT INTO index_versions(version_id, embedding_fingerprint, schema_version, status) "
            f"VALUES ({self._placeholder}, {self._placeholder}, {self._placeholder}, {self._placeholder})",
            (
                version.version_id,
                version.embedding_fingerprint,
                version.schema_version,
                version.status.value,
            ),
        )

    def get_index_version(self, version_id: str) -> IndexVersion:
        row = self._fetchone(
            "SELECT version_id, embedding_fingerprint, schema_version, status "
            f"FROM index_versions WHERE version_id={self._placeholder}",
            (version_id,),
        )
        if row is None:
            raise RepositoryNotFoundError(version_id)
        return IndexVersion(
            version_id=row[0],
            embedding_fingerprint=row[1],
            schema_version=int(row[2]),
            status=IndexVersionStatus(row[3]),
        )

    def activate_alias(self, alias: str, version_id: str) -> IndexVersion:
        if not alias.strip():
            raise ValueError("index alias cannot be empty")
        version = self.get_index_version(version_id)
        self._execute(
            "UPDATE index_versions SET status=? WHERE version_id IN "
            "(SELECT version_id FROM index_aliases WHERE alias=?)".replace("?", self._placeholder),
            (IndexVersionStatus.READY.value, alias),
        )
        self._execute(
            f"UPDATE index_versions SET status={self._placeholder} WHERE version_id={self._placeholder}",
            (IndexVersionStatus.ACTIVE.value, version_id),
        )
        upsert = (
            "INSERT INTO index_aliases(alias, version_id) "
            f"VALUES ({self._placeholder}, {self._placeholder}) "
            "ON CONFLICT(alias) DO UPDATE SET version_id=excluded.version_id"
        )
        self._execute(upsert, (alias, version_id))
        return self.get_index_version(version.version_id)

    def get_active_alias(self, alias: str) -> IndexVersion:
        row = self._fetchone(
            f"SELECT version_id FROM index_aliases WHERE alias={self._placeholder}",
            (alias,),
        )
        if row is None:
            raise RepositoryNotFoundError(alias)
        return self.get_index_version(row[0])

    def rollback_alias(self, alias: str, version_id: str) -> IndexVersion:
        if self._fetchone(
            f"SELECT version_id FROM index_aliases WHERE alias={self._placeholder}",
            (alias,),
        ) is None:
            raise RepositoryNotFoundError(alias)
        return self.activate_alias(alias, version_id)


def sqlite_connection(database: str | Path) -> Any:
    """打开 SQLite 连接，但不让 sqlite3 泄露到应用层。"""
    import sqlite3

    connection = sqlite3.connect(str(database))
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
