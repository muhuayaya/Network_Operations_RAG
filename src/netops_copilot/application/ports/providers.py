"""独立于具体 SDK 的 provider 能力描述。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class Capability(StrEnum):
    """已注册基础设施适配器提供的应用能力。"""

    LLM = "llm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    DENSE_SEARCH = "dense-search"
    LEXICAL_SEARCH = "lexical-search"
    METADATA_STORAGE = "metadata-storage"
    DEVICE_OBSERVATION = "device-observation"


class ProviderKind(StrEnum):
    """provider 适配器的主要角色。"""

    LLM = "llm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    DENSE_SEARCH = "dense-search"
    LEXICAL_SEARCH = "lexical-search"
    METADATA_STORAGE = "metadata-storage"
    DEVICE_OBSERVATION = "device-observation"


class ProviderHealth(StrEnum):
    """启动校验期间报告的 provider 就绪状态。"""

    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RESERVED = "reserved"


class DistanceMetric(StrEnum):
    """构成 Embedding 索引指纹的距离指标。"""

    COSINE = "cosine"
    DOT_PRODUCT = "dot-product"
    EUCLIDEAN = "euclidean"


class EmbeddingNormalization(StrEnum):
    """与索引兼容性相关的向量规范化策略。"""

    L2 = "l2"
    NONE = "none"


PRIMARY_CAPABILITY_BY_KIND = {
    ProviderKind.LLM: Capability.LLM,
    ProviderKind.EMBEDDING: Capability.EMBEDDING,
    ProviderKind.RERANKER: Capability.RERANKER,
    ProviderKind.DENSE_SEARCH: Capability.DENSE_SEARCH,
    ProviderKind.LEXICAL_SEARCH: Capability.LEXICAL_SEARCH,
    ProviderKind.METADATA_STORAGE: Capability.METADATA_STORAGE,
    ProviderKind.DEVICE_OBSERVATION: Capability.DEVICE_OBSERVATION,
}


class ProviderCompatibilityError(ValueError):
    """选定的描述符无法提供安全 Profile 时抛出的异常。"""


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """向启动校验和 doctor 输出暴露的静态 provider 契约。"""

    name: str
    kind: ProviderKind
    version: str
    capabilities: frozenset[Capability]
    health: ProviderHealth
    model_id: str | None = None
    embedding_dimension: int | None = None
    normalization: EmbeddingNormalization | None = None
    distance_metric: DistanceMetric | None = None
    supports_streaming: bool = False
    supports_filters: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.version:
            raise ValueError("provider descriptor requires a name and version")
        primary_capability = PRIMARY_CAPABILITY_BY_KIND[self.kind]
        if primary_capability not in self.capabilities:
            raise ValueError(f"{self.kind.value} must declare {primary_capability.value}")
        if self.kind is ProviderKind.EMBEDDING:
            if self.health is ProviderHealth.RESERVED:
                if any(
                    value is not None
                    for value in (self.embedding_dimension, self.normalization, self.distance_metric)
                ):
                    raise ValueError("reserved embedding providers cannot claim index metadata")
            else:
                if self.embedding_dimension is None or self.embedding_dimension <= 0:
                    raise ValueError("embedding providers require a positive dimension")
                if self.normalization is None or self.distance_metric is None:
                    raise ValueError("embedding providers require normalization and distance metric")
        elif any(
            value is not None
            for value in (self.embedding_dimension, self.normalization, self.distance_metric)
        ):
            raise ValueError("embedding metadata is only valid for embedding providers")

    @property
    def is_usable(self) -> bool:
        """判断此描述符能否满足必需的启动能力。"""
        return self.health in {ProviderHealth.READY, ProviderHealth.DEGRADED}


def validate_provider_compatibility(
    descriptors: Iterable[ProviderDescriptor], required_capabilities: frozenset[Capability]
) -> None:
    """拒绝重复名称、不可用 provider 和缺失必需能力。"""
    collected = tuple(descriptors)
    names = [descriptor.name for descriptor in collected]
    if len(set(names)) != len(names):
        raise ProviderCompatibilityError("provider names must be unique")
    usable_capabilities = frozenset(
        capability
        for descriptor in collected
        if descriptor.is_usable
        for capability in descriptor.capabilities
    )
    missing = required_capabilities - usable_capabilities
    if missing:
        missing_names = ", ".join(sorted(capability.value for capability in missing))
        raise ProviderCompatibilityError(f"missing usable capabilities: {missing_names}")
