"""结构化模型 provider 端口不变量和模拟结果覆盖测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.ports.models import (
    EmbeddingRequest,
    EmbeddingResult,
    LLMRequest,
    LLMResult,
    ModelErrorCode,
    ModelStatus,
    RerankResult,
    UsageMetadata,
)


class ModelPortTests(unittest.TestCase):
    def test_success_results_carry_structured_usage(self) -> None:
        usage = UsageMetadata(input_tokens=10, output_tokens=4, total_tokens=14, estimated_cost_usd=0.001)
        llm = LLMResult(ModelStatus.SUCCESS, text="evidence", usage=usage)
        embedding = EmbeddingResult(ModelStatus.SUCCESS, vectors=((0.1, 0.2),), usage=usage)
        rerank = RerankResult(ModelStatus.SUCCESS, scores=(("chunk-1", 0.9),), usage=usage)
        self.assertEqual(llm.usage.total_tokens, 14)
        self.assertEqual(embedding.vectors[0], (0.1, 0.2))
        self.assertEqual(rerank.scores[0][0], "chunk-1")

    def test_malformed_timeout_and_unavailable_are_explicit(self) -> None:
        malformed = LLMResult(ModelStatus.MALFORMED, error_code=ModelErrorCode.INVALID_RESPONSE)
        timeout = EmbeddingResult(ModelStatus.TIMEOUT, error_code=ModelErrorCode.TIMEOUT)
        unavailable = RerankResult(ModelStatus.UNAVAILABLE, error_code=ModelErrorCode.UNAVAILABLE)
        self.assertEqual(malformed.status, ModelStatus.MALFORMED)
        self.assertEqual(timeout.error_code, ModelErrorCode.TIMEOUT)
        self.assertEqual(unavailable.status, ModelStatus.UNAVAILABLE)

    def test_request_and_response_shapes_reject_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            LLMRequest("", max_tokens=0)
        with self.assertRaises(ValueError):
            EmbeddingRequest(())
        with self.assertRaises(ValueError):
            EmbeddingResult(ModelStatus.SUCCESS, vectors=((0.1,), (0.1, 0.2)))
