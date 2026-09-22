"""带安全秘密处理重试机制的 OpenAI 兼容 LLM 和 Embedding 适配器。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from netops_copilot.application.ports.models import (
    EmbeddingPort,
    EmbeddingRequest,
    EmbeddingResult,
    LLMPort,
    LLMRequest,
    LLMResult,
    ModelErrorCode,
    ModelStatus,
    UsageMetadata,
)
from netops_copilot.infrastructure.observability.redaction import resolve_environment_secret
from netops_copilot.infrastructure.providers.errors import (
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)


class OpenAITransport(Protocol):
    def __call__(
        self,
        path: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        """发送一次请求并返回解码后的 JSON 对象。"""


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    """不在 Profile 文件中解析秘密值的 provider 配置。"""

    model: str
    api_key_env: str
    max_retries: int = 2
    base_path: str = ""

    def __post_init__(self) -> None:
        if not self.model.strip() or not self.api_key_env.strip() or self.max_retries < 0:
            raise ValueError("provider config requires model, secret reference and non-negative retries")


class OpenAICompatibleLLMAdapter(LLMPort):
    """带有限重试和响应校验的 Chat Completions 适配器。"""

    def __init__(
        self,
        transport: OpenAITransport,
        config: OpenAICompatibleConfig,
        *,
        environment: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._transport = transport
        self._config = config
        self._api_key = resolve_environment_secret(config.api_key_env, environment)
        self._sleep = sleep or (lambda _: None)

    def complete(self, request: LLMRequest, timeout_seconds: float = 30.0) -> LLMResult:
        payload = {
            "model": self._config.model,
            "messages": [
                *([{"role": "system", "content": request.system}] if request.system else []),
                {"role": "user", "content": request.prompt},
            ],
            "max_tokens": request.max_tokens,
        }
        response = self._call("/chat/completions", payload, timeout_seconds)
        if isinstance(response, LLMResult):
            return response
        try:
            choices = response["choices"]
            text = choices[0]["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise TypeError
            return LLMResult(ModelStatus.SUCCESS, text=text, usage=_usage(response.get("usage")))
        except (KeyError, IndexError, TypeError, ValueError):
            return LLMResult(ModelStatus.MALFORMED, error_code=ModelErrorCode.INVALID_RESPONSE)

    def _call(self, path: str, payload: Mapping[str, Any], timeout_seconds: float) -> Mapping[str, Any] | LLMResult:
        for attempt in range(self._config.max_retries + 1):
            try:
                return self._transport(
                    f"{self._config.base_path}{path}",
                    payload,
                    {"Authorization": f"Bearer {self._api_key}"},
                    timeout_seconds,
                )
            except RateLimitError:
                if attempt >= self._config.max_retries:
                    return LLMResult(ModelStatus.UNAVAILABLE, error_code=ModelErrorCode.RATE_LIMITED)
                self._sleep(0.0)
            except ProviderTimeoutError:
                if attempt >= self._config.max_retries:
                    return LLMResult(ModelStatus.TIMEOUT, error_code=ModelErrorCode.TIMEOUT)
            except ProviderUnavailableError:
                return LLMResult(ModelStatus.UNAVAILABLE, error_code=ModelErrorCode.UNAVAILABLE)
        return LLMResult(ModelStatus.UNAVAILABLE, error_code=ModelErrorCode.UNKNOWN)


class OpenAICompatibleEmbeddingAdapter(EmbeddingPort):
    """共享同一传输层和安全秘密重试策略的 Embedding 适配器。"""

    def __init__(
        self,
        transport: OpenAITransport,
        config: OpenAICompatibleConfig,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._transport = transport
        self._config = config
        self._api_key = resolve_environment_secret(config.api_key_env, environment)

    def embed(self, request: EmbeddingRequest, timeout_seconds: float = 30.0) -> EmbeddingResult:
        payload = {"model": self._config.model, "input": list(request.texts)}
        for attempt in range(self._config.max_retries + 1):
            try:
                response = self._transport(
                    f"{self._config.base_path}/embeddings",
                    payload,
                    {"Authorization": f"Bearer {self._api_key}"},
                    timeout_seconds,
                )
                data = response["data"]
                vectors = tuple(tuple(float(value) for value in item["embedding"]) for item in data)
                if len(vectors) != len(request.texts):
                    raise ValueError("embedding count mismatch")
                return EmbeddingResult(ModelStatus.SUCCESS, vectors=vectors, usage=_usage(response.get("usage")))
            except RateLimitError:
                if attempt >= self._config.max_retries:
                    return EmbeddingResult(ModelStatus.UNAVAILABLE, error_code=ModelErrorCode.RATE_LIMITED)
            except ProviderTimeoutError:
                if attempt >= self._config.max_retries:
                    return EmbeddingResult(ModelStatus.TIMEOUT, error_code=ModelErrorCode.TIMEOUT)
            except ProviderUnavailableError:
                return EmbeddingResult(ModelStatus.UNAVAILABLE, error_code=ModelErrorCode.UNAVAILABLE)
            except (KeyError, IndexError, TypeError, ValueError):
                return EmbeddingResult(ModelStatus.MALFORMED, error_code=ModelErrorCode.INVALID_RESPONSE)
        return EmbeddingResult(ModelStatus.UNAVAILABLE, error_code=ModelErrorCode.UNKNOWN)


def _usage(value: Any) -> UsageMetadata | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return UsageMetadata(
            input_tokens=int(value.get("prompt_tokens", value.get("input_tokens", 0))),
            output_tokens=int(value.get("completion_tokens", value.get("output_tokens", 0))),
            total_tokens=int(value.get("total_tokens", 0)),
        )
    except (TypeError, ValueError):
        return None
