"""模拟 OpenAI 兼容 provider 行为和秘密安全测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.ports.models import (
    EmbeddingRequest,
    LLMRequest,
    ModelErrorCode,
    ModelStatus,
)
from netops_copilot.infrastructure.observability.redaction import MissingSecretError
from netops_copilot.infrastructure.providers.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleEmbeddingAdapter,
    OpenAICompatibleLLMAdapter,
    ProviderTimeoutError,
    RateLimitError,
)


class _Transport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls = 0
        self.headers: list[dict[str, str]] = []

    def __call__(self, path: str, payload: object, headers: dict[str, str], timeout_seconds: float) -> object:
        self.calls += 1
        self.headers.append(headers)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class OpenAICompatibleTests(unittest.TestCase):
    def test_llm_retries_rate_limit_and_parses_usage(self) -> None:
        transport = _Transport(
            [RateLimitError(), {"choices": [{"message": {"content": "answer"}}], "usage": {"total_tokens": 3}}]
        )
        adapter = OpenAICompatibleLLMAdapter(
            transport,
            OpenAICompatibleConfig("demo", "API_KEY", max_retries=1),
            environment={"API_KEY": "secret-value"},
        )
        result = adapter.complete(LLMRequest("question"))
        self.assertEqual(result.status, ModelStatus.SUCCESS)
        self.assertEqual(transport.calls, 2)
        self.assertEqual(transport.headers[0]["Authorization"], "Bearer secret-value")

    def test_embedding_malformed_and_timeout_are_classified(self) -> None:
        malformed = OpenAICompatibleEmbeddingAdapter(
            _Transport([{"data": [{"embedding": [0.1]}]}]),
            OpenAICompatibleConfig("demo", "API_KEY"),
            environment={"API_KEY": "secret"},
        )
        self.assertEqual(malformed.embed(EmbeddingRequest(("a", "b"))).error_code, ModelErrorCode.INVALID_RESPONSE)
        timeout = OpenAICompatibleLLMAdapter(
            _Transport([ProviderTimeoutError(), ProviderTimeoutError()]),
            OpenAICompatibleConfig("demo", "API_KEY", max_retries=1),
            environment={"API_KEY": "secret"},
        )
        self.assertEqual(timeout.complete(LLMRequest("q")).status, ModelStatus.TIMEOUT)

    def test_missing_secret_error_does_not_include_a_value(self) -> None:
        with self.assertRaises(MissingSecretError) as context:
            OpenAICompatibleLLMAdapter(_Transport([]), OpenAICompatibleConfig("demo", "MISSING"), environment={})
        self.assertNotIn("secret", str(context.exception))
