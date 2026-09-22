"""协调索引激活安全测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.indexing import VersionedIndexManager
from netops_copilot.application.indexing_service import CoordinatedIndexer, IndexingError
from netops_copilot.application.ports.indexing import IndexableChunk
from netops_copilot.application.ports.repositories import IndexVersion
from netops_copilot.infrastructure.persistence.memory import InMemoryMetadataRepository


class _Writer:
    def __init__(self, *, fail: bool = False, wrong_count: bool = False) -> None:
        self.fail = fail
        self.wrong_count = wrong_count
        self.records: dict[str, list[str]] = {}

    def index_chunks(self, version_id: str, chunks: tuple[IndexableChunk, ...] | list[IndexableChunk]) -> int:
        if self.fail:
            raise RuntimeError("backend unavailable")
        self.records[version_id] = [chunk.chunk_id for chunk in chunks]
        return len(chunks) - 1 if self.wrong_count else len(chunks)

    def count(self, version_id: str) -> int:
        return len(self.records.get(version_id, []))

    def sample_readback(self, version_id: str, chunk_ids: list[str]) -> bool:
        return set(chunk_ids).issubset(set(self.records.get(version_id, [])))


class CoordinatedIndexingTests(unittest.TestCase):
    def setUp(self) -> None:
        repository = InMemoryMetadataRepository()
        self.manager = VersionedIndexManager(repository)
        self.manager.register(IndexVersion("v1", "model:8:l2:cosine", 1))
        self.manager.register(IndexVersion("v2", "model:8:l2:cosine", 1))
        self.manager.activate("v1")
        self.chunks = [IndexableChunk("chunk-1", "OSPF", {}), IndexableChunk("chunk-2", "ACL", {})]

    def test_activation_requires_both_counts_and_readback(self) -> None:
        report = CoordinatedIndexer(_Writer(), _Writer(), self.manager).index_and_activate("v2", self.chunks)
        self.assertEqual(report.expected_count, 2)
        self.assertEqual(self.manager.active().version.version_id, "v2")

    def test_partial_storage_never_replaces_previous_active_version(self) -> None:
        with self.assertRaises(IndexingError):
            CoordinatedIndexer(_Writer(), _Writer(wrong_count=True), self.manager).index_and_activate("v2", self.chunks)
        self.assertEqual(self.manager.active().version.version_id, "v1")
