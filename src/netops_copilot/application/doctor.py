"""供 doctor CLI 使用的安全依赖就绪报告。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from os import environ

from netops_copilot.application.ports.providers import (
    ProviderDescriptor,
    ProviderHealth,
)
from netops_copilot.application.startup import (
    REQUIRED_RUNTIME_CAPABILITIES,
    IndexDescriptor,
    StartupValidationError,
    validate_startup,
)
from netops_copilot.bootstrap import ApplicationContainer
from netops_copilot.infrastructure.observability.redaction import resolve_environment_secret


class DoctorStatus(StrEnum):
    """doctor 命令对外暴露的总体就绪状态。"""

    HEALTHY = "healthy"
    OPTIONAL_DEGRADED = "optional-degraded"
    REQUIRED_UNAVAILABLE = "required-unavailable"


@dataclass(frozen=True, slots=True)
class DependencyCheck:
    """不包含秘密值的安全依赖结果。"""

    name: str
    required: bool
    ready: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        """序列化 doctor 依赖，不包含隐藏的运行时对象。"""
        return {
            "name": self.name,
            "required": self.required,
            "ready": self.ready,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """机器可读且不泄露秘密的就绪摘要。"""

    profile: str
    status: DoctorStatus
    active_capabilities: tuple[str, ...]
    dependencies: tuple[DependencyCheck, ...]

    def to_dict(self) -> dict[str, object]:
        """为 CLI 和未来 REST 输出序列化报告。"""
        return {
            "profile": self.profile,
            "status": self.status.value,
            "active_capabilities": list(self.active_capabilities),
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
        }


def doctor_report(
    container: ApplicationContainer,
    active_index: IndexDescriptor | None = None,
    optional_providers: tuple[ProviderDescriptor, ...] = (),
) -> DoctorReport:
    """检查必需和可选依赖，但不解析或打印秘密。"""
    dependencies: list[DependencyCheck] = []
    required_ready = True
    optional_ready = True

    for provider in container.providers:
        ready = provider.health in {ProviderHealth.READY, ProviderHealth.DEGRADED}
        dependencies.append(
            DependencyCheck(
                name=provider.name,
                required=True,
                ready=ready,
                detail=provider.health.value,
            )
        )
        required_ready = required_ready and ready

    for provider in optional_providers:
        ready = provider.health in {ProviderHealth.READY, ProviderHealth.DEGRADED}
        dependencies.append(
            DependencyCheck(
                name=provider.name,
                required=False,
                ready=ready,
                detail=provider.health.value,
            )
        )
        optional_ready = optional_ready and ready

    for model_provider in (container.settings.llm, container.settings.embedding):
        if model_provider.api_key_env is None:
            continue
        try:
            resolve_environment_secret(model_provider.api_key_env, environ)
        except ValueError as error:
            dependencies.append(
                DependencyCheck(
                    name=f"secret:{model_provider.api_key_env}",
                    required=True,
                    ready=False,
                    detail=str(error),
                )
            )
            required_ready = False

    if active_index is None:
        dependencies.append(
            DependencyCheck(
                name="active-index",
                required=True,
                ready=False,
                detail="no active index is configured",
            )
        )
        required_ready = False
    else:
        try:
            validate_startup(
                container.providers,
                REQUIRED_RUNTIME_CAPABILITIES,
                active_index,
                container.settings.index_schema_version,
                container.settings.device_access_mode,
            )
        except StartupValidationError as error:
            dependencies.append(
                DependencyCheck(
                    name="active-index",
                    required=True,
                    ready=False,
                    detail=str(error),
                )
            )
            required_ready = False
        else:
            dependencies.append(
                DependencyCheck(
                    name="active-index",
                    required=True,
                    ready=True,
                    detail="schema and embedding fingerprint match",
                )
            )

    active_capabilities = tuple(
        sorted(
            capability.value
            for provider in container.providers
            if provider.is_usable
            for capability in provider.capabilities
        )
    )
    if not required_ready:
        status = DoctorStatus.REQUIRED_UNAVAILABLE
    elif not optional_ready:
        status = DoctorStatus.OPTIONAL_DEGRADED
    else:
        status = DoctorStatus.HEALTHY
    return DoctorReport(
        profile=container.settings.profile.value,
        status=status,
        active_capabilities=active_capabilities,
        dependencies=tuple(dependencies),
    )
