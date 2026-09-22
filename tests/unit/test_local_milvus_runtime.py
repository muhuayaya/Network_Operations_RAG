"""local-milvus backend, configuration, and composition tests without Docker."""

from __future__ import annotations

import sqlite3
import unittest
from typing import Any

from netops_copilot.application.indexing import VersionedIndexManager
from netops_copilot.application.local_milvus_runtime import local_milvus_doctor
from netops_copilot.application.ports.indexing import IndexableChunk
from netops_copilot.application.ports.models import EmbeddingRequest, EmbeddingResult, ModelStatus
from netops_copilot.application.ports.repositories import IndexVersion
from netops_copilot.infrastructure.local_milvus import LocalMilvusSettings
from netops_copilot.infrastructure.persistence.postgres import PostgresMetadataRepository
from netops_copilot.infrastructure.retrieval.milvus import (
    MilvusDenseIndexWriter,
    MilvusSparseBm25IndexWriter,
)


class _Embedding:
    def embed(self, request: EmbeddingRequest, timeout_seconds: float = 30.0) -> EmbeddingResult:
        return EmbeddingResult(
            ModelStatus.SUCCESS,
            vectors=tuple((1.0, 0.0) for _ in request.texts),
        )


class _Collection:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def upsert(self, *, data: list[dict[str, Any]]) -> None:
        for item in data:
            self.items[str(item["chunk_id"])] = item

    def count(self) -> int:
        return len(self.items)

    def get(self, *, ids: list[str], **_: Any) -> dict[str, list[str]]:
        return {"ids": [item for item in ids if item in self.items]}

    def load(self) -> None:
        return None


class _MilvusClient:
    def __init__(self, collection_name: str | None = None) -> None:
        self.collection_name = collection_name

    def list_collections(self) -> list[str]:
        return [self.collection_name] if self.collection_name else []

    def has_collection(self, collection_name: str) -> bool:
        return collection_name == self.collection_name

    def describe_collection(self, collection_name: str) -> dict[str, Any]:
        fields = ["chunk_id", "text", "embedding", "sparse", "site_id", "device_id", "vendor", "os_version", "security_level", "source_id", "source_locator", "content_hash"]
        return {"collection_name": collection_name, "fields": [{"name": field} for field in fields]}

    def load_collection(self, collection_name: str) -> None:
        return None

    def get_collection_stats(self, collection_name: str) -> dict[str, int]:
        return {"row_count": 1}

    def query(self, **_: Any) -> list[dict[str, str]]:
        return [{"chunk_id": "chunk-1"}]


class LocalMilvusRuntimeTests(unittest.TestCase):
    def test_settings_builds_dsn_without_exposing_password_in_diagnostics(self) -> None:
        settings = LocalMilvusSettings.from_environment(
            {
                "POSTGRES_PASSWORD": "secret-value",
                "MILVUS_URI": "http://127.0.0.1:19530",
            }
        )
        self.assertEqual(settings.milvus_uri, "http://127.0.0.1:19530")
        self.assertNotIn("secret-value", settings.milvus_uri)
        self.assertIn("postgresql://", settings.postgres_dsn)

    def test_writers_share_one_collection_and_verify_counts(self) -> None:
        collection = _Collection()
        chunks = (
            IndexableChunk("chunk-1", "OSPF ExStart", {"vendor": "H3C"}),
            IndexableChunk("chunk-2", "MTU check", {"vendor": "Huawei"}),
        )
        dense = MilvusDenseIndexWriter(collection, _Embedding(), dimension=2, batch_size=1)
        lexical = MilvusSparseBm25IndexWriter(collection)

        self.assertEqual(dense.index_chunks("v1", chunks), 2)
        self.assertEqual(lexical.index_chunks("v1", chunks), 2)
        self.assertEqual(dense.count("v1"), 2)
        self.assertTrue(lexical.sample_readback("v1", ["chunk-1", "chunk-2"]))

    def test_doctor_reports_active_alias_only_after_backend_checks(self) -> None:
        connection = sqlite3.connect(":memory:")
        repository = PostgresMetadataRepository(connection)
        manager = VersionedIndexManager(repository)
        manager.register(IndexVersion("v1", "4c5f", 1))
        manager.activate("v1")
        report = local_milvus_doctor(
            environment={"POSTGRES_PASSWORD": "test", "DASHSCOPE_API_KEY": "test"},
            milvus_client=_MilvusClient(manager.active().collection_name),
            postgres_connection=connection,
        )
        self.assertEqual(report.status.value, "healthy")
        self.assertTrue(any(item.name == "active-index" and item.ready for item in report.dependencies))
        repository.close()


if __name__ == "__main__":
    unittest.main()
