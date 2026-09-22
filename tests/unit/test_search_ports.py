"""验证与后端无关的检索契约。"""

from __future__ import annotations

import unittest

from netops_copilot.application.ports.search import (
    SearchCandidate,
    SearchChannel,
    SearchErrorCode,
    SearchFilters,
    SearchResult,
    SearchStatus,
)


class SearchPortTests(unittest.TestCase):
    def test_empty_result_is_distinct_from_backend_failure(self) -> None:
        empty = SearchResult.empty()
        failed = SearchResult.failed(SearchErrorCode.UNAVAILABLE)

        self.assertEqual(empty.status, SearchStatus.EMPTY)
        self.assertEqual(failed.status, SearchStatus.FAILED)
        self.assertEqual(failed.error_code, SearchErrorCode.UNAVAILABLE)
        self.assertFalse(empty.candidates)
        self.assertFalse(failed.candidates)

    def test_candidate_and_filters_are_immutable_and_structured(self) -> None:
        filters = SearchFilters(site_id="site-gz-dc", vendor="Huawei")
        candidate = SearchCandidate(
            chunk_id="chunk-1",
            channel=SearchChannel.DENSE,
            rank=1,
            raw_score=0.95,
            metadata={"site_id": "site-gz-dc"},
        )

        self.assertEqual(filters.as_mapping(), {"site_id": "site-gz-dc", "vendor": "Huawei"})
        self.assertEqual(SearchResult.matches([candidate]).status, SearchStatus.MATCHES)
        with self.assertRaises(ValueError):
            SearchFilters(site_id=" ")
        with self.assertRaises(ValueError):
            SearchCandidate("chunk-1", SearchChannel.DENSE, 0, 0.1, {})

    def test_result_invariants_prevent_ambiguous_states(self) -> None:
        with self.assertRaises(ValueError):
            SearchResult(SearchStatus.MATCHES)
        with self.assertRaises(ValueError):
            SearchResult(
                SearchStatus.EMPTY,
                candidates=(SearchCandidate("chunk-1", SearchChannel.LEXICAL, 1, 1.0, {}),),
            )
