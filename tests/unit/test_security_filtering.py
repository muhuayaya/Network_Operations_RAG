"""主体、站点和安全级别过滤测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.authorization import filter_knowledge_chunks, filter_search_result
from netops_copilot.application.ports.search import (
    SearchCandidate,
    SearchChannel,
    SearchFilters,
    SearchResult,
)
from netops_copilot.application.query import QueryMode, QueryService
from netops_copilot.domain.inventory import DataSecurityLevel
from netops_copilot.domain.knowledge import KnowledgeChunk
from netops_copilot.domain.shared.identity import Principal, SecurityLevel


class _Search:
    def __init__(self, result: SearchResult) -> None:
        self.result = result
        self.filters: SearchFilters | None = None

    def search(self, query: str, filters: SearchFilters, limit: int = 10) -> SearchResult:
        del query, limit
        self.filters = filters
        return self.result


class SecurityFilteringTests(unittest.TestCase):
    def test_basic_principal_is_constrained_before_backend_and_restricted_rows_are_removed(self) -> None:
        restricted = SearchCandidate(
            "restricted-1",
            SearchChannel.LEXICAL,
            1,
            1.0,
            {"site_id": "site-gz-dc", "security_level": "restricted"},
        )
        backend = _Search(SearchResult.matches((restricted,)))
        service = QueryService(backend, backend)
        principal = Principal("basic", SecurityLevel.BASIC, frozenset({"site-gz-dc"}))

        result = service.search(
            query="restricted maintenance",
            query_vector=(1.0,),
            filters=SearchFilters(site_id="site-gz-dc"),
            mode=QueryMode.LEXICAL_ONLY,
            principal=principal,
        )

        self.assertEqual(backend.filters.security_level if backend.filters else None, "internal")
        self.assertEqual(result.candidates, ())

    def test_restricted_principal_can_read_restricted_chunk_but_basic_cannot(self) -> None:
        chunk = KnowledgeChunk(
            chunk_id="restricted-1",
            source_id="source-1",
            version="v1",
            text="restricted evidence",
            source_locator="source.md#1",
            content_hash="hash",
            security_level=DataSecurityLevel.RESTRICTED,
            metadata={"site_id": "site-gz-dc"},
        )
        basic = Principal("basic", SecurityLevel.BASIC, frozenset({"site-gz-dc"}))
        restricted = Principal("restricted", SecurityLevel.RESTRICTED, frozenset({"site-gz-dc"}))
        self.assertEqual(filter_knowledge_chunks(basic, (chunk,)), ())
        self.assertEqual(filter_knowledge_chunks(restricted, (chunk,)), (chunk,))
        result = SearchResult.matches(
            (
                SearchCandidate(
                    "restricted-1",
                    SearchChannel.LEXICAL,
                    1,
                    1.0,
                    {"site_id": "site-gz-dc", "security_level": "restricted"},
                ),
            )
        )
        self.assertEqual(filter_search_result(basic, result), SearchResult.empty())


if __name__ == "__main__":
    unittest.main()
