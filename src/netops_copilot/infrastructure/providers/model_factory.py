"""为问答服务构造百炼和本地 OpenAI-compatible LLM。"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from netops_copilot.application.grounded_answers import ModelSource
from netops_copilot.application.ports.models import (
    LLMPort,
    LLMRequest,
    LLMResult,
    ModelErrorCode,
    ModelStatus,
)
from netops_copilot.infrastructure.observability.redaction import MissingSecretError
from netops_copilot.infrastructure.providers.http_transport import OpenAICompatibleHttpTransport
from netops_copilot.infrastructure.providers.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleLLMAdapter,
)
from netops_copilot.settings import ProfileSettings


class _LazyLLM:
    """延迟读取配置，避免一个未配置模型阻塞另一个模型的检索启动。"""

    def __init__(self, factory: Callable[[], LLMPort]) -> None:
        self._factory = factory

    def complete(self, request: LLMRequest, timeout_seconds: float = 30.0) -> LLMResult:
        try:
            adapter = self._factory()
        except (MissingSecretError, ValueError, KeyError):
            return LLMResult(ModelStatus.UNAVAILABLE, error_code=ModelErrorCode.UNAVAILABLE)
        return adapter.complete(request, timeout_seconds)


def create_answer_models(
    settings: ProfileSettings,
    environment: Mapping[str, str] | None = None,
) -> Mapping[str, LLMPort]:
    """返回稳定的模型选择映射，不在构造阶段打印或暴露秘密。"""

    values = dict(environment or {})

    def dashscope() -> LLMPort:
        if settings.llm.base_url is None or settings.llm.api_key_env is None:
            raise ValueError("DashScope LLM profile is incomplete")
        return OpenAICompatibleLLMAdapter(
            OpenAICompatibleHttpTransport(settings.llm.base_url),
            OpenAICompatibleConfig(settings.llm.model, settings.llm.api_key_env),
            environment=values,
        )

    def local() -> LLMPort:
        base_url = values.get("LOCAL_LLM_BASE_URL", "").strip()
        model = values.get("LOCAL_LLM_MODEL", "").strip()
        if not base_url or not model:
            raise ValueError("LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL must be configured")
        local_key_env = "LOCAL_LLM_API_KEY"
        local_values = {**values, local_key_env: values.get(local_key_env, "local")}
        return OpenAICompatibleLLMAdapter(
            OpenAICompatibleHttpTransport(base_url),
            OpenAICompatibleConfig(model, local_key_env),
            environment=local_values,
        )

    return {
        ModelSource.DASHSCOPE.value: _LazyLLM(dashscope),
        ModelSource.LOCAL.value: _LazyLLM(local),
    }


__all__ = ["create_answer_models"]
