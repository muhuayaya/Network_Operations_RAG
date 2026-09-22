"""Composition root for the real local-milvus profile."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netops_copilot.application.demo_runtime import load_demo_index_inputs
from netops_copilot.application.demo_services import DemoApplicationServices
from netops_copilot.application.doctor import DependencyCheck, DoctorReport, DoctorStatus
from netops_copilot.application.grounded_answers import GroundedAnswerService, KeywordReranker
from netops_copilot.application.indexing import VersionedIndexManager
from netops_copilot.application.indexing_service import CoordinatedIndexer
from netops_copilot.application.ports.indexing import IndexableChunk
from netops_copilot.application.ports.models import EmbeddingPort, EmbeddingRequest
from netops_copilot.application.ports.repositories import IndexVersion, RepositoryNotFoundError
from netops_copilot.application.query import QueryService
from netops_copilot.application.startup import embedding_fingerprint
from netops_copilot.bootstrap import bootstrap
from netops_copilot.infrastructure.local_milvus import (
    LocalMilvusConfigurationError,
    LocalMilvusSettings,
    MilvusRuntimeDependencyError,
    create_milvus_client,
    ensure_milvus_collection,
    open_milvus_collection,
    validate_milvus_collection,
)
from netops_copilot.infrastructure.persistence.postgres import PostgresMetadataRepository
from netops_copilot.infrastructure.persistence.postgres_connection import (
    PostgresConnectionError,
    check_postgres,
    connect_postgres,
)
from netops_copilot.infrastructure.providers.http_transport import OpenAICompatibleHttpTransport
from netops_copilot.infrastructure.providers.model_factory import create_answer_models
from netops_copilot.infrastructure.providers.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleEmbeddingAdapter,
)
from netops_copilot.infrastructure.retrieval.milvus import (
    MilvusDenseIndexWriter,
    MilvusDenseSearchAdapter,
    MilvusSparseBm25IndexWriter,
    MilvusSparseBm25SearchAdapter,
)
from netops_copilot.interfaces.cli.lifecycle import ingest_dataset
from netops_copilot.settings import ProfileName, ProfileSettings, load_profile


class LocalMilvusRuntimeError(RuntimeError):
    """Raised when local-milvus cannot construct a complete runtime."""


@dataclass(frozen=True, slots=True)
class LocalMilvusBuildReport:
    profile: ProfileName
    version_id: str
    collection_name: str
    embedding_fingerprint: str
    source_count: int
    chunk_count: int
    dense_count: int
    lexical_count: int
    active_alias: str


def build_local_milvus_runtime(
    profile: ProfileName,
    dataset_root: Path,
    runtime_dir: Path,
    version_id: str | None = None,
    *,
    embedding: EmbeddingPort | None = None,
    milvus_client: Any | None = None,
    postgres_connection: Any | None = None,
    environment: Mapping[str, str] | None = None,
) -> LocalMilvusBuildReport:
    settings = _require_local_profile(profile)
    connection_settings = LocalMilvusSettings.from_environment(environment)
    inputs = load_demo_index_inputs(dataset_root)
    if not inputs.chunks:
        raise ValueError("dataset produced no indexable chunks")
    ingest_summary = ingest_dataset(dataset_root, runtime_dir)
    client = milvus_client or create_milvus_client(connection_settings)
    connection = postgres_connection or connect_postgres(
        connection_settings.postgres_dsn,
        connect_timeout=connection_settings.postgres_connect_timeout,
    )
    repository = PostgresMetadataRepository(connection, close_connection=postgres_connection is None)
    try:
        manager = VersionedIndexManager(repository)
        selected_embedding = embedding or _create_embedding(settings, connection_settings.environment)
        descriptor = next(
            provider for provider in bootstrap(profile).providers if provider.kind.value == "embedding"
        )
        fingerprint = embedding_fingerprint(descriptor)
        selected_version = version_id or _new_version_id(inputs.chunks)
        collection_name = manager.register(
            IndexVersion(selected_version, fingerprint, settings.index_schema_version)
        )
        collection = ensure_milvus_collection(
            client,
            collection_name,
            dimension=settings.embedding.dimension,
        )
        dense = MilvusDenseIndexWriter(
            collection,
            selected_embedding,
            dimension=settings.embedding.dimension,
        )
        lexical = MilvusSparseBm25IndexWriter(collection)
        report = CoordinatedIndexer(dense, lexical, manager).index_and_activate(
            selected_version,
            inputs.chunks,
        )
    finally:
        repository.close()
    return LocalMilvusBuildReport(
        profile=profile,
        version_id=report.version_id,
        collection_name=collection_name,
        embedding_fingerprint=fingerprint,
        source_count=ingest_summary.source_count,
        chunk_count=report.expected_count,
        dense_count=report.dense_count,
        lexical_count=report.lexical_count,
        active_alias=report.active.alias,
    )


def create_local_milvus_services(
    profile: ProfileName,
    runtime_dir: Path,
    *,
    embedding: EmbeddingPort | None = None,
    milvus_client: Any | None = None,
    postgres_connection: Any | None = None,
    environment: Mapping[str, str] | None = None,
) -> DemoApplicationServices:
    settings = _require_local_profile(profile)
    connection_settings = LocalMilvusSettings.from_environment(environment)
    client = milvus_client or create_milvus_client(connection_settings)
    connection = postgres_connection or connect_postgres(
        connection_settings.postgres_dsn,
        connect_timeout=connection_settings.postgres_connect_timeout,
    )
    repository = PostgresMetadataRepository(connection, close_connection=postgres_connection is None)
    try:
        manager = VersionedIndexManager(repository)
        active = manager.active()
        descriptor = next(
            provider for provider in bootstrap(profile).providers if provider.kind.value == "embedding"
        )
        fingerprint = embedding_fingerprint(descriptor)
        manager.assert_query_compatible(
            collection=active.collection_name,
            embedding_fingerprint=fingerprint,
            schema_version=settings.index_schema_version,
        )
    finally:
        repository.close()
    collection = open_milvus_collection(client, active.collection_name)
    report = validate_milvus_collection(collection, dimension=settings.embedding.dimension)
    if not report.healthy:
        raise LocalMilvusRuntimeError(report.reason or "Milvus schema is incompatible")
    selected_embedding = embedding or _create_embedding(settings, connection_settings.environment)
    query_service = QueryService(
        MilvusDenseSearchAdapter(
            collection,
            anns_field="embedding",
            search_params={"metric_type": "COSINE"},
        ),
        MilvusSparseBm25SearchAdapter(
            collection,
            anns_field="sparse",
            search_params={"metric_type": "BM25"},
        ),
        reranker=KeywordReranker(),
    )
    return DemoApplicationServices(
        query_service=query_service,
        vectorizer=_EmbeddingVectorizer(selected_embedding),
        answer_service=GroundedAnswerService(
            query_service,
            _EmbeddingVectorizer(selected_embedding),
            create_answer_models(settings, connection_settings.environment),
        ),
        dependencies={
            "embedding": True,
            "milvus": True,
            "postgresql": True,
            "dense-search": True,
            "lexical-search": True,
            "active-index": True,
        },
    )


def local_milvus_doctor(
    *,
    environment: Mapping[str, str] | None = None,
    milvus_client: Any | None = None,
    postgres_connection: Any | None = None,
) -> DoctorReport:
    """Perform actual local backend checks and return a safe DoctorReport."""

    container = bootstrap(ProfileName.LOCAL_MILVUS)
    dependencies = [
        DependencyCheck(provider.name, True, provider.is_usable, provider.health.value)
        for provider in container.providers
    ]
    required_ready = all(item.ready for item in dependencies)
    try:
        connection_settings = LocalMilvusSettings.from_environment(environment)
    except LocalMilvusConfigurationError as error:
        dependencies.append(DependencyCheck("configuration", True, False, str(error)))
        return _doctor(container, dependencies, False)
    if not _embedding_configured(container.settings, connection_settings.environment):
        dependencies.append(
            DependencyCheck(
                f"secret:{container.settings.embedding.api_key_env}",
                True,
                False,
                "required environment variable is missing",
            )
        )
        required_ready = False
    client = milvus_client
    if client is None:
        try:
            client = create_milvus_client(connection_settings)
            client.list_collections()
            dependencies.append(DependencyCheck("milvus", True, True, "reachable"))
        except (MilvusRuntimeDependencyError, OSError, RuntimeError, ValueError) as error:
            dependencies.append(DependencyCheck("milvus", True, False, str(error)))
            required_ready = False
    else:
        dependencies.append(DependencyCheck("milvus", True, True, "injected client"))
    connection = postgres_connection
    if connection is None:
        try:
            connection = connect_postgres(
                connection_settings.postgres_dsn,
                connect_timeout=connection_settings.postgres_connect_timeout,
            )
            ready, detail = check_postgres(connection)
            dependencies.append(DependencyCheck("postgresql", True, ready, detail))
            required_ready = required_ready and ready
        except PostgresConnectionError as error:
            dependencies.append(DependencyCheck("postgresql", True, False, str(error)))
            required_ready = False
    else:
        dependencies.append(DependencyCheck("postgresql", True, True, "injected connection"))
    try:
        if client is None or connection is None:
            raise LocalMilvusRuntimeError("backend connection is unavailable")
        repository = PostgresMetadataRepository(connection, close_connection=False)
        try:
            active = VersionedIndexManager(repository).active()
        except (RepositoryNotFoundError, OSError, RuntimeError, ValueError):
            dependencies.append(DependencyCheck("active-index", True, False, "no active index is configured"))
            required_ready = False
        else:
            collection = open_milvus_collection(client, active.collection_name)
            schema_report = validate_milvus_collection(
                collection,
                dimension=container.settings.embedding.dimension,
            )
            if not schema_report.healthy:
                dependencies.append(DependencyCheck("active-index", True, False, schema_report.reason or "schema mismatch"))
                required_ready = False
            else:
                dependencies.append(DependencyCheck("active-index", True, True, "schema and alias match"))
    except (MilvusRuntimeDependencyError, OSError, RuntimeError, ValueError) as error:
        dependencies.append(DependencyCheck("active-index", True, False, str(error)))
        required_ready = False
    finally:
        if postgres_connection is None and connection is not None:
            connection.close()
    return _doctor(container, dependencies, required_ready)


class _EmbeddingVectorizer:
    def __init__(self, embedding: EmbeddingPort) -> None:
        self._embedding = embedding

    def __call__(self, query: str) -> Sequence[float]:
        result = self._embedding.embed(EmbeddingRequest((query,)))
        if result.status.value != "success" or not result.vectors:
            code = result.error_code.value if result.error_code is not None else "unknown"
            raise LocalMilvusRuntimeError(f"Embedding 服务调用失败：{code}")
        return result.vectors[0]


def _create_embedding(settings: ProfileSettings, environment: Mapping[str, str] | None) -> EmbeddingPort:
    if settings.embedding.api_key_env is None or settings.embedding.base_url is None:
        raise LocalMilvusRuntimeError("Embedding 服务缺少 api_key_env 或 base_url 配置")
    return OpenAICompatibleEmbeddingAdapter(
        OpenAICompatibleHttpTransport(settings.embedding.base_url),
        OpenAICompatibleConfig(settings.embedding.model, settings.embedding.api_key_env),
        environment=environment,
    )


def _require_local_profile(profile: ProfileName) -> ProfileSettings:
    settings = load_profile(profile)
    if settings.profile is not ProfileName.LOCAL_MILVUS:
        raise ValueError("the local runtime supports only the local-milvus profile")
    return settings


def _embedding_configured(settings: ProfileSettings, environment: Mapping[str, str] | None) -> bool:
    return bool(settings.embedding.api_key_env and environment and environment.get(settings.embedding.api_key_env))


def _doctor(container: Any, dependencies: list[DependencyCheck], required_ready: bool) -> DoctorReport:
    return DoctorReport(
        profile=container.settings.profile.value,
        status=DoctorStatus.HEALTHY if required_ready else DoctorStatus.REQUIRED_UNAVAILABLE,
        active_capabilities=tuple(sorted(capability.value for provider in container.providers if provider.is_usable for capability in provider.capabilities)),
        dependencies=tuple(dependencies),
    )


def _new_version_id(chunks: Sequence[IndexableChunk]) -> str:
    digest = hashlib.sha256("\n".join(item.chunk_id for item in chunks).encode("utf-8")).hexdigest()[:10]
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return f"local_{timestamp}_{digest}"


__all__ = [
    "LocalMilvusBuildReport",
    "LocalMilvusRuntimeError",
    "build_local_milvus_runtime",
    "create_local_milvus_services",
    "local_milvus_doctor",
]
