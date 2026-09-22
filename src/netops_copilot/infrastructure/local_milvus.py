"""Optional local Milvus client, schema, and health helpers.

The base package does not import ``pymilvus``.  This module is loaded only by
the local-milvus composition root, so demo-lite and unit tests remain offline.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote, urlparse


class LocalMilvusConfigurationError(ValueError):
    """Raised when local backend configuration is incomplete or invalid."""


class MilvusRuntimeDependencyError(RuntimeError):
    """Raised when the optional Milvus SDK or service is unavailable."""


@dataclass(frozen=True, slots=True)
class LocalMilvusSettings:
    """Validated, non-secret connection settings for the local runtime."""

    milvus_uri: str
    milvus_token: str
    postgres_dsn: str
    postgres_connect_timeout: int = 5
    environment: Mapping[str, str] | None = None

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        env_file: Path | None = None,
    ) -> LocalMilvusSettings:
        values = _environment(environment, env_file)
        uri = values.get("MILVUS_URI", "http://127.0.0.1:19530").strip()
        token = values.get("MILVUS_TOKEN", "root:Milvus").strip()
        if not uri or urlparse(uri).scheme not in {"http", "https", "tcp", "grpc", "grpcs"}:
            raise LocalMilvusConfigurationError("MILVUS_URI must be an absolute Milvus URI")
        if not token:
            raise LocalMilvusConfigurationError("MILVUS_TOKEN must not be empty")
        dsn = values.get("POSTGRES_DSN", "").strip()
        if not dsn:
            password = values.get("POSTGRES_PASSWORD", "").strip()
            if not password:
                raise LocalMilvusConfigurationError(
                    "POSTGRES_DSN or POSTGRES_PASSWORD must be configured"
                )
            user = values.get("POSTGRES_USER", "netops").strip() or "netops"
            database = values.get("POSTGRES_DB", "netops").strip() or "netops"
            host = values.get("POSTGRES_HOST", "127.0.0.1").strip() or "127.0.0.1"
            port = values.get("POSTGRES_PORT", "5432").strip() or "5432"
            dsn = (
                f"postgresql://{quote(user)}:{quote(password, safe='')}@"
                f"{host}:{port}/{quote(database)}"
            )
        try:
            timeout = int(values.get("POSTGRES_CONNECT_TIMEOUT", "5"))
        except ValueError as error:
            raise LocalMilvusConfigurationError(
                "POSTGRES_CONNECT_TIMEOUT must be an integer"
            ) from error
        if timeout < 1:
            raise LocalMilvusConfigurationError("POSTGRES_CONNECT_TIMEOUT must be positive")
        safe_environment = dict(values)
        return cls(uri, token, dsn, timeout, safe_environment)


@dataclass(frozen=True, slots=True)
class MilvusSchemaReport:
    healthy: bool
    collection_name: str
    fields: tuple[str, ...] = ()
    reason: str | None = None


_METADATA_FIELDS = (
    "site_id",
    "device_id",
    "vendor",
    "os_version",
    "security_level",
    "source_id",
    "source_locator",
    "content_hash",
)
_REQUIRED_FIELDS = ("chunk_id", "text", "embedding", "sparse", *_METADATA_FIELDS)


class MilvusCollectionHandle:
    """Small duck-typed collection facade used by existing adapters/writers."""

    def __init__(self, client: Any, collection_name: str) -> None:
        self._client = client
        self.name = collection_name
        self.schema = _schema_view(client.describe_collection(collection_name))

    def load(self) -> None:
        self._client.load_collection(self.name)

    def flush(self) -> None:
        self._client.flush(self.name)

    def upsert(self, *, data: list[dict[str, Any]]) -> Any:
        return self._client.upsert(collection_name=self.name, data=data)

    def count(self) -> int:
        stats = self._client.get_collection_stats(self.name)
        return int(stats.get("row_count", 0))

    def get(self, *, ids: list[str], **_: Any) -> dict[str, list[str]]:
        rows = self._client.query(
            collection_name=self.name,
            ids=ids,
            output_fields=["chunk_id"],
        )
        return {"ids": [str(row["chunk_id"]) for row in rows if "chunk_id" in row]}

    def search(self, *, data: list[Any], anns_field: str, param: Mapping[str, Any], limit: int, expr: str, output_fields: list[str]) -> Any:
        search_params = dict(param)
        return self._client.search(
            collection_name=self.name,
            data=data,
            anns_field=anns_field,
            search_params=search_params,
            limit=limit,
            filter=expr,
            output_fields=output_fields,
        )


def create_milvus_client(settings: LocalMilvusSettings) -> Any:
    try:
        from pymilvus import MilvusClient  # type: ignore[import-untyped]
    except ImportError as error:
        raise MilvusRuntimeDependencyError(
            "Milvus runtime is unavailable; install the local-milvus extra"
        ) from error
    try:
        return MilvusClient(uri=settings.milvus_uri, token=settings.milvus_token)
    except Exception as error:
        raise MilvusRuntimeDependencyError("Milvus client connection failed") from error


def ensure_milvus_collection(
    client: Any,
    collection_name: str,
    *,
    dimension: int,
) -> MilvusCollectionHandle:
    """Create or validate one version-scoped Dense+BM25 collection."""

    if client.has_collection(collection_name):
        handle = MilvusCollectionHandle(client, collection_name)
        report = validate_milvus_collection(handle, dimension=dimension)
        if not report.healthy:
            raise MilvusRuntimeDependencyError(report.reason or "Milvus schema is incompatible")
        handle.load()
        return handle

    try:
        from pymilvus import DataType, Function, FunctionType

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=512)
        schema.add_field("text", DataType.VARCHAR, max_length=65535, enable_analyzer=True)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)
        schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
        for field in _METADATA_FIELDS:
            schema.add_field(field, DataType.VARCHAR, max_length=4096, nullable=True)
        schema.add_function(
            Function(
                name="text_bm25",
                input_field_names=["text"],
                output_field_names=["sparse"],
                function_type=FunctionType.BM25,
            )
        )
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        index_params.add_index(
            field_name="sparse",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
        )
        client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )
        handle = MilvusCollectionHandle(client, collection_name)
        handle.load()
        return handle
    except MilvusRuntimeDependencyError:
        raise
    except Exception as error:
        raise MilvusRuntimeDependencyError("Milvus collection creation failed") from error


def open_milvus_collection(client: Any, collection_name: str) -> MilvusCollectionHandle:
    """Open an existing collection without creating a fallback or new index."""

    if not client.has_collection(collection_name):
        raise MilvusRuntimeDependencyError(f"Milvus collection does not exist: {collection_name}")
    handle = MilvusCollectionHandle(client, collection_name)
    handle.load()
    return handle


def validate_milvus_collection(collection: Any, *, dimension: int) -> MilvusSchemaReport:
    fields = tuple(
        str(getattr(field, "name", field.get("name", "")))
        if isinstance(field, Mapping)
        else str(getattr(field, "name", field))
        for field in getattr(getattr(collection, "schema", None), "fields", ())
    )
    missing = sorted(set(_REQUIRED_FIELDS) - set(fields))
    if missing:
        return MilvusSchemaReport(False, str(getattr(collection, "name", "unknown")), fields, f"missing fields: {', '.join(missing)}")
    return MilvusSchemaReport(True, str(getattr(collection, "name", "unknown")), fields)


def _schema_view(description: Mapping[str, Any]) -> Any:
    fields = description.get("fields", []) if isinstance(description, Mapping) else []
    return SimpleNamespace(
        fields=[SimpleNamespace(name=str(item.get("name", item.get("fieldName", "")))) for item in fields]
    )


def _environment(
    environment: Mapping[str, str] | None,
    env_file: Path | None,
) -> dict[str, str]:
    if environment is not None:
        return dict(environment)
    values: dict[str, str] = {}
    candidate = env_file or Path.cwd() / ".env"
    if candidate.is_file():
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    values.update(os.environ)
    return values


__all__ = [
    "LocalMilvusConfigurationError",
    "LocalMilvusSettings",
    "MilvusCollectionHandle",
    "MilvusRuntimeDependencyError",
    "MilvusSchemaReport",
    "create_milvus_client",
    "ensure_milvus_collection",
    "open_milvus_collection",
    "validate_milvus_collection",
]
