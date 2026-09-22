"""不连接真实服务的 Milvus 适配器映射和标量过滤测试。"""

from __future__ import annotations

import unittest
from typing import ClassVar

from netops_copilot.application.ports.search import SearchFilters, SearchStatus
from netops_copilot.infrastructure.retrieval.milvus import (
    MilvusDenseSearchAdapter,
    MilvusSparseBm25SearchAdapter,
    build_milvus_filter,
)


class _Field:
    def __init__(self, name: str) -> None:
        self.name = name


class _Schema:
    fields: ClassVar[list[_Field]] = [_Field("chunk_id"), _Field("site_id"), _Field("vendor")]


class _FakeMilvusCollection:
    name = "demo_v1"
    schema = _Schema()

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> list[list[dict[str, object]]]:
        self.calls.append(kwargs)
        return [[{"id": "chunk-1", "distance": 0.1, "entity": {"site_id": "site-gz-dc", "text": "OSPF evidence"}}]]


class MilvusAdapterTests(unittest.TestCase):
    def test_scalar_filters_are_allow_listed_and_quoted(self) -> None:
        expression = build_milvus_filter(SearchFilters(site_id='site"gz', vendor="Huawei"))
        self.assertEqual(expression, 'site_id == "site\\\"gz" and vendor == "Huawei"')

    def test_dense_adapter_maps_hits_and_inspects_schema(self) -> None:
        collection = _FakeMilvusCollection()
        adapter = MilvusDenseSearchAdapter(collection, anns_field="embedding")
        result = adapter.search([0.1, 0.2], SearchFilters(site_id="site-gz-dc"))

        self.assertEqual(result.status, SearchStatus.MATCHES)
        self.assertEqual(result.candidates[0].chunk_id, "chunk-1")
        self.assertEqual(result.candidates[0].raw_score, -0.1)
        self.assertEqual(result.candidates[0].text, "OSPF evidence")
        self.assertEqual(collection.calls[0]["expr"], 'site_id == "site-gz-dc"')
        self.assertTrue(adapter.health_check(("chunk_id", "site_id")).healthy)

    def test_sparse_adapter_uses_lexical_channel(self) -> None:
        adapter = MilvusSparseBm25SearchAdapter(_FakeMilvusCollection(), anns_field="sparse")
        result = adapter.search("OSPF ExStart", SearchFilters())
        self.assertEqual(result.status, SearchStatus.MATCHES)
        self.assertEqual(result.candidates[0].channel.value, "lexical")
