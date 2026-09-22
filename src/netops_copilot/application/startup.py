"""在接口接收流量前执行快速失败的启动校验。"""

from __future__ import annotations

from dataclasses import dataclass

from netops_copilot.application.ports.providers import (
    Capability,
    ProviderCompatibilityError,
    ProviderDescriptor,
    ProviderKind,
    validate_provider_compatibility,
)


class StartupValidationError(ValueError):
    """选定的运行时依赖无法让 Profile 安全提供服务。"""


REQUIRED_RUNTIME_CAPABILITIES = frozenset(
    {
        Capability.LLM,
        Capability.EMBEDDING,
        Capability.DENSE_SEARCH,
        Capability.LEXICAL_SEARCH,
        Capability.METADATA_STORAGE,
        Capability.DEVICE_OBSERVATION,
    }
)


@dataclass(frozen=True, slots=True)
class IndexDescriptor:
    """保护 Embedding 兼容性所需的活动索引元数据。"""

    collection_name: str
    schema_version: int
    embedding_fingerprint: str


def embedding_fingerprint(descriptor: ProviderDescriptor) -> str:
    """创建活动索引使用的不可变 Embedding 空间标识。"""
    if descriptor.kind is not ProviderKind.EMBEDDING:
        raise ValueError("embedding fingerprint requires an embedding provider")
    if (
        descriptor.model_id is None
        or descriptor.embedding_dimension is None
        or descriptor.normalization is None
        or descriptor.distance_metric is None
    ):
        raise ValueError("embedding provider does not declare complete index metadata")
    return ":".join(
        (
            descriptor.model_id,
            str(descriptor.embedding_dimension),
            descriptor.normalization.value,
            descriptor.distance_metric.value,
        )
    )


def validate_startup(
    providers: tuple[ProviderDescriptor, ...],
    required_capabilities: frozenset[Capability],
    active_index: IndexDescriptor,
    expected_index_schema_version: int,
    device_access_mode: str,
) -> None:
    """校验 provider、索引兼容性和设备不变更策略。"""
    if device_access_mode != "readonly":
        raise StartupValidationError("device access mode must be readonly")
    try:
        validate_provider_compatibility(providers, required_capabilities)
    except ProviderCompatibilityError as error:
        raise StartupValidationError(str(error)) from error
    embedding_providers = [provider for provider in providers if provider.kind is ProviderKind.EMBEDDING]
    if len(embedding_providers) != 1:
        raise StartupValidationError("exactly one embedding provider must be selected")
    if active_index.schema_version != expected_index_schema_version:
        raise StartupValidationError("active index schema version is incompatible")
    if active_index.embedding_fingerprint != embedding_fingerprint(embedding_providers[0]):
        raise StartupValidationError("active index embedding fingerprint is incompatible")
