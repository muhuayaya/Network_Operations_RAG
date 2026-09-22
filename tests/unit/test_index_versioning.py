"""Embedding 指纹集合和别名生命周期测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.indexing import (
    IndexCompatibilityError,
    VersionedIndexManager,
    collection_name,
)
from netops_copilot.application.ports.repositories import IndexVersion
from netops_copilot.infrastructure.persistence.memory import InMemoryMetadataRepository


class IndexVersioningTests(unittest.TestCase):
    def test_collection_name_contains_safe_embedding_fingerprint_and_version(self) -> None:
        self.assertEqual(
            collection_name("netops_chunks", "bge-m3:1024:l2:cosine", "v1"),
            "netops_chunks__bge_m3_1024_l2_cosine__v1",
        )

    def test_collection_name_stays_within_backend_identifier_limit(self) -> None:
        value = collection_name("netops_chunks", "text-embedding-v4:1024:l2:cosine", "v" + "x" * 100)
        self.assertLessEqual(len(value), 63)
        self.assertTrue(value.startswith("netops_chunks__text_embedding_v4"))

    def test_alias_switch_and_rollback_are_retained(self) -> None:
        manager = VersionedIndexManager(InMemoryMetadataRepository())
        manager.register(IndexVersion("v1", "model-a:8:l2:cosine", 1))
        manager.register(IndexVersion("v2", "model-b:16:l2:cosine", 1))

        first = manager.activate("v1")
        second = manager.activate("v2")
        rolled_back = manager.rollback("v1")

        self.assertEqual(first.version.version_id, "v1")
        self.assertEqual(second.version.version_id, "v2")
        self.assertEqual(rolled_back.version.version_id, "v1")

    def test_embedding_change_cannot_query_old_collection(self) -> None:
        manager = VersionedIndexManager(InMemoryMetadataRepository())
        manager.register(IndexVersion("v1", "model-a:8:l2:cosine", 1))
        manager.register(IndexVersion("v2", "model-b:16:l2:cosine", 1))
        active = manager.activate("v1")

        with self.assertRaises(IndexCompatibilityError):
            manager.assert_query_compatible(
                collection=active.collection_name,
                embedding_fingerprint="model-b:16:l2:cosine",
                schema_version=1,
            )

        manager.activate("v2")
        with self.assertRaises(IndexCompatibilityError):
            manager.assert_query_compatible(
                collection=active.collection_name,
                embedding_fingerprint="model-a:8:l2:cosine",
                schema_version=1,
            )
