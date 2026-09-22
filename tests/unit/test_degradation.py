"""失败分类和查询降级状态测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.degradation import DegradationState, classify_query
from netops_copilot.application.ports.models import LLMResult, ModelErrorCode, ModelStatus
from netops_copilot.application.ports.search import SearchErrorCode, SearchResult


class DegradationTests(unittest.TestCase):
    def test_zero_evidence_is_not_backend_failure(self) -> None:
        result = classify_query(SearchResult.empty(), SearchResult.empty())
        self.assertEqual(result.state, DegradationState.ZERO_EVIDENCE)
        self.assertFalse(result.failures)

    def test_partial_and_total_unavailability_are_distinct(self) -> None:
        partial = classify_query(SearchResult.failed(SearchErrorCode.TIMEOUT), SearchResult.empty())
        total = classify_query(SearchResult.failed(SearchErrorCode.TIMEOUT), SearchResult.failed(SearchErrorCode.UNAVAILABLE))
        llm_partial = classify_query(SearchResult.empty(), SearchResult.empty(), LLMResult(ModelStatus.TIMEOUT, error_code=ModelErrorCode.TIMEOUT))
        self.assertEqual(partial.state, DegradationState.PARTIAL)
        self.assertEqual(total.state, DegradationState.TOTAL_UNAVAILABLE)
        self.assertEqual(llm_partial.state, DegradationState.PARTIAL)
