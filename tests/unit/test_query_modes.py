"""查询模式和可选 reranker 降级测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.ports.models import ModelStatus, RerankResult
from netops_copilot.application.ports.search import (
    SearchCandidate,
    SearchChannel,
    SearchFilters,
    SearchResult,
)
from netops_copilot.application.query import QueryMode, QueryService


class _Search:
    def __init__(self, dense: SearchResult, lexical: SearchResult) -> None:
        self.dense_result = dense
        self.lexical_result = lexical

    def search(self, query_vector: list[float], filters: SearchFilters, limit: int = 10) -> SearchResult:
        return self.dense_result


class _Lexical(_Search):
    def search(self, query: str, filters: SearchFilters, limit: int = 10) -> SearchResult:
        return self.lexical_result


class _Reranker:
    def __init__(self, result: RerankResult) -> None:
        self.result = result

    def rerank(self, request: object, timeout_seconds: float = 10.0) -> RerankResult:
        return self.result


def _candidate(chunk_id: str, channel: SearchChannel, rank: int) -> SearchCandidate:
    return SearchCandidate(chunk_id, channel, rank, 1.0, {})


class QueryModeTests(unittest.TestCase):
    def setUp(self) -> None:
        dense = SearchResult.matches([_candidate("a", SearchChannel.DENSE, 1)])
        lexical = SearchResult.matches([_candidate("a", SearchChannel.LEXICAL, 1), _candidate("b", SearchChannel.LEXICAL, 2)])
        self.service = QueryService(_Search(dense, lexical), _Lexical(dense, lexical))

    def test_dense_lexical_and_hybrid_modes(self) -> None:
        filters = SearchFilters()
        self.assertEqual(len(self.service.search(query="q", query_vector=[1.0], filters=filters, mode=QueryMode.DENSE_ONLY).candidates), 1)
        self.assertEqual(len(self.service.search(query="q", query_vector=[1.0], filters=filters, mode=QueryMode.LEXICAL_ONLY).candidates), 2)
        hybrid = self.service.search(query="q", query_vector=[1.0], filters=filters)
        self.assertEqual(hybrid.candidates[0].chunk_id, "a")

    def test_unavailable_reranker_preserves_fused_candidates_with_marker(self) -> None:
        result = self.service.search(
            query="q",
            query_vector=[1.0],
            filters=SearchFilters(),
            mode=QueryMode.HYBRID_RERANK,
            candidate_texts={"a": "A", "b": "B"},
        )
        self.assertEqual([candidate.chunk_id for candidate in result.candidates], ["a", "b"])
        self.assertIn("reranker:unavailable", result.degradation)

    def test_available_reranker_can_change_order(self) -> None:
        dense = SearchResult.matches([_candidate("a", SearchChannel.DENSE, 1)])
        lexical = SearchResult.matches([_candidate("a", SearchChannel.LEXICAL, 1), _candidate("b", SearchChannel.LEXICAL, 2)])
        service = QueryService(
            _Search(dense, lexical),
            _Lexical(dense, lexical),
            _Reranker(RerankResult(ModelStatus.SUCCESS, scores=(("b", 0.9), ("a", 0.1)))),
        )
        result = service.search(query="q", query_vector=[1.0], filters=SearchFilters(), mode=QueryMode.HYBRID_RERANK, candidate_texts={"a": "A", "b": "B"})
        self.assertEqual(result.candidates[0].chunk_id, "b")

    def test_low_confidence_dense_only_result_becomes_zero_evidence(self) -> None:
        dense = SearchResult.matches([SearchCandidate("weak", SearchChannel.DENSE, 1, -0.8, {})])
        lexical = SearchResult.empty()
        service = QueryService(
            _Search(dense, lexical),
            _Lexical(dense, lexical),
            minimum_dense_score=-0.4,
        )

        result = service.search(
            query="unknown",
            query_vector=[1.0],
            filters=SearchFilters(),
        )

        self.assertEqual(result.state.value, "zero-evidence")
        self.assertEqual(result.candidates, ())

    def test_lexical_hit_keeps_a_low_confidence_dense_candidate(self) -> None:
        dense = SearchResult.matches([SearchCandidate("weak", SearchChannel.DENSE, 1, -0.8, {})])
        lexical = SearchResult.matches([SearchCandidate("lexical", SearchChannel.LEXICAL, 1, 1.0, {})])
        service = QueryService(
            _Search(dense, lexical),
            _Lexical(dense, lexical),
            minimum_dense_score=-0.4,
        )

        result = service.search(
            query="known",
            query_vector=[1.0],
            filters=SearchFilters(),
        )

        self.assertEqual(result.state.value, "healthy")
        self.assertTrue(result.candidates)
