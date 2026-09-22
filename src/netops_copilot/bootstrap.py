"""按 Profile 选择 provider 的显式组合根。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from netops_copilot.application.ports.providers import (
    Capability,
    DistanceMetric,
    EmbeddingNormalization,
    ProviderDescriptor,
    ProviderHealth,
    ProviderKind,
)
from netops_copilot.application.ports.registry import ProviderRegistry
from netops_copilot.application.startup import (
    REQUIRED_RUNTIME_CAPABILITIES,
    IndexDescriptor,
    validate_startup,
)
from netops_copilot.settings import ProfileName, ProfileSettings, load_profile


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    """为一个 Profile 组装的应用级依赖。"""

    settings: ProfileSettings
    providers: tuple[ProviderDescriptor, ...]
    registry: ProviderRegistry


def _descriptor(
    kind: ProviderKind,
    provider: str,
    settings: ProfileSettings,
    health: ProviderHealth = ProviderHealth.READY,
) -> ProviderDescriptor:
    """创建 provider 描述符，但不导入任何 provider SDK。"""
    capability = Capability(kind.value)
    if kind is ProviderKind.EMBEDDING:
        if health is ProviderHealth.RESERVED:
            return ProviderDescriptor(
                name=f"{kind.value}:{provider}",
                kind=kind,
                version="reserved",
                capabilities=frozenset({capability}),
                health=health,
            )
        return ProviderDescriptor(
            name=f"{kind.value}:{provider}",
            kind=kind,
            version="configured",
            capabilities=frozenset({capability}),
            health=health,
            model_id=settings.embedding.model,
            embedding_dimension=settings.embedding.dimension,
            normalization=EmbeddingNormalization.L2,
            distance_metric=DistanceMetric.COSINE,
        )
    return ProviderDescriptor(
        name=f"{kind.value}:{provider}",
        kind=kind,
        version="reserved" if health is ProviderHealth.RESERVED else "configured",
        capabilities=frozenset({capability}),
        health=health,
        model_id=settings.llm.model if kind is ProviderKind.LLM and health is not ProviderHealth.RESERVED else None,
        supports_filters=kind in {ProviderKind.DENSE_SEARCH, ProviderKind.LEXICAL_SEARCH},
    )


def _descriptor_factory(
    kind: ProviderKind, provider: str, health: ProviderHealth
) -> Callable[[ProfileSettings], ProviderDescriptor]:
    """为显式注册表注册绑定 provider 元数据。"""

    def factory(settings: ProfileSettings) -> ProviderDescriptor:
        return _descriptor(kind, provider, settings, health)

    return factory


def create_builtin_registry() -> ProviderRegistry:
    """显式注册所有内置 provider；导入模块不会产生注册副作用。"""
    registry = ProviderRegistry()
    for kind, providers in (
        (ProviderKind.LLM, ("fake", "local-reserved", "openai-compatible")),
        (ProviderKind.EMBEDDING, ("fake", "local-reserved", "openai-compatible")),
        (ProviderKind.RERANKER, ("local-reserved",)),
        (ProviderKind.DENSE_SEARCH, ("chroma", "in-memory", "milvus")),
        (ProviderKind.LEXICAL_SEARCH, ("in-memory", "milvus-bm25", "sqlite-fts5")),
        (ProviderKind.METADATA_STORAGE, ("postgresql", "sqlite", "sqlite-memory")),
        (ProviderKind.DEVICE_OBSERVATION, ("simulator",)),
    ):
        for provider in providers:
            health = ProviderHealth.RESERVED if provider == "local-reserved" else ProviderHealth.READY
            registry.register(
                kind,
                provider,
                _descriptor_factory(kind, provider, health),
            )
    return registry


def bootstrap(profile: ProfileName, registry: ProviderRegistry | None = None) -> ApplicationContainer:
    """加载一个 Profile，并显式构造其中选定的 provider 描述符。"""
    settings = load_profile(profile)
    selected = (
        (ProviderKind.LLM, settings.llm.provider),
        (ProviderKind.EMBEDDING, settings.embedding.provider),
        (ProviderKind.DENSE_SEARCH, settings.dense_search.provider),
        (ProviderKind.LEXICAL_SEARCH, settings.lexical_search.provider),
        (ProviderKind.METADATA_STORAGE, settings.metadata_store.provider),
        (ProviderKind.DEVICE_OBSERVATION, settings.device_observation.provider),
    )
    active_registry = registry or create_builtin_registry()
    providers = tuple(
        active_registry.create(kind, provider, settings) for kind, provider in selected
    )
    return ApplicationContainer(settings=settings, providers=providers, registry=active_registry)


def bootstrap_validated(profile: ProfileName, active_index: IndexDescriptor) -> ApplicationContainer:
    """仅在选定的运行时依赖兼容后构建服务容器。"""
    container = bootstrap(profile)
    validate_startup(
        container.providers,
        REQUIRED_RUNTIME_CAPABILITIES,
        active_index,
        container.settings.index_schema_version,
        container.settings.device_access_mode,
    )
    return container
