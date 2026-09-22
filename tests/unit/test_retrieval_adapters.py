"""demo-lite Dense 和 Lexical 适配器契约检查。"""

from __future__ import annotations

import unittest

from netops_copilot.application.ports.search import SearchErrorCode, SearchFilters, SearchStatus
from netops_copilot.infrastructure.retrieval.chroma import ChromaDenseSearchAdapter
from netops_copilot.infrastructure.retrieval.sqlite_fts import SqliteFts5SearchAdapter


class _FakeChromaCollection:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def query(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return self.response


class RetrievalAdapterTests(unittest.TestCase):
    def test_chroma_maps_results_and_authorized_filters(self) -> None:
        collection = _FakeChromaCollection(
            {
                "ids": [["chunk-1"]],
                "distances": [[0.2]],
                "metadatas": [[{"site_id": "site-gz-dc"}]],
                "documents": [["OSPF ExStart evidence"]],
            }
        )
        adapter = ChromaDenseSearchAdapter(collection)
        result = adapter.search([0.1, 0.2], SearchFilters(site_id="site-gz-dc"))

        self.assertEqual(result.status, SearchStatus.MATCHES)
        self.assertEqual(result.candidates[0].chunk_id, "chunk-1")
        self.assertEqual(result.candidates[0].text, "OSPF ExStart evidence")
        self.assertEqual(collection.calls[0]["where"], {"site_id": "site-gz-dc"})

    def test_chroma_empty_and_failure_are_explicit(self) -> None:
        empty = ChromaDenseSearchAdapter(_FakeChromaCollection({"ids": [[]]}))
        self.assertEqual(empty.search([0.1], SearchFilters()).status, SearchStatus.EMPTY)
        invalid = empty.search([], SearchFilters())
        self.assertEqual(invalid.error_code, SearchErrorCode.INVALID_REQUEST)

    def test_sqlite_fts5_searches_bm25_and_filters_metadata(self) -> None:
        adapter = SqliteFts5SearchAdapter()
        adapter.upsert("chunk-1", "OSPF neighbor stuck in ExStart", {"site_id": "site-gz-dc"})
        adapter.upsert("chunk-2", "ACL sequence ordering", {"site_id": "site-hz-core"})

        result = adapter.search("OSPF ExStart", SearchFilters(site_id="site-gz-dc"))
        self.assertEqual(result.status, SearchStatus.MATCHES)
        self.assertEqual(result.candidates[0].chunk_id, "chunk-1")
        self.assertEqual(result.candidates[0].text, "OSPF neighbor stuck in ExStart")
        self.assertEqual(
            adapter.search("zzzzzz", SearchFilters()).status,
            SearchStatus.EMPTY,
        )
        self.assertEqual(adapter.search("\"", SearchFilters()).status, SearchStatus.FAILED)
        adapter.close()

    def test_sqlite_fts5_treats_hyphenated_user_text_as_terms(self) -> None:
        adapter = SqliteFts5SearchAdapter()
        adapter.upsert("cisco-acl", "Cisco-compatible ACL concept", {})

        result = adapter.search("如何核对 Cisco-compatible ACL？", SearchFilters())

        self.assertEqual(result.status, SearchStatus.MATCHES)
        self.assertEqual(result.candidates[0].chunk_id, "cisco-acl")
        adapter.close()
