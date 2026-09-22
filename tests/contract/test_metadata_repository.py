"""元数据仓储适配器契约套件。"""

from __future__ import annotations

import sqlite3
import unittest

from netops_copilot.application.ports.repositories import (
    IndexVersion,
    IndexVersionStatus,
    RepositoryNotFoundError,
)
from netops_copilot.infrastructure.persistence.memory import InMemoryMetadataRepository
from netops_copilot.infrastructure.persistence.postgres import PostgresMetadataRepository
from netops_copilot.infrastructure.persistence.sqlite import SqliteMetadataRepository


class MetadataRepositoryContractTests(unittest.TestCase):
    """内存适配器定义 SQLite/PostgreSQL 应遵循的行为。"""

    def setUp(self) -> None:
        self.repository = InMemoryMetadataRepository()

    def test_create_and_read_metadata_records(self) -> None:
        value = {"device_id": "hw-01"}
        self.repository.save_inventory("device-1", value)
        self.repository.save_source("source-1", value)
        self.repository.save_job("job-1", value)
        self.repository.save_trace("trace-1", value)

        self.assertEqual(self.repository.get_inventory("device-1"), value)
        self.assertEqual(self.repository.get_source("source-1"), value)
        self.assertEqual(self.repository.get_job("job-1"), value)
        self.assertEqual(self.repository.get_trace("trace-1"), value)
        with self.assertRaises(RepositoryNotFoundError):
            self.repository.get_source("missing")

    def test_version_activation_and_rollback_are_explicit(self) -> None:
        first = IndexVersion("v1", "model:8:l2:cosine", 1)
        second = IndexVersion("v2", "model:8:l2:cosine", 1)
        self.repository.save_index_version(first)
        self.repository.save_index_version(second)

        self.assertEqual(self.repository.activate_alias("active", "v1").status, IndexVersionStatus.ACTIVE)
        self.assertEqual(self.repository.activate_alias("active", "v2").version_id, "v2")
        rolled_back = self.repository.rollback_alias("active", "v1")

        self.assertEqual(rolled_back.version_id, "v1")
        self.assertEqual(self.repository.get_active_alias("active").version_id, "v1")
        self.assertEqual(self.repository.get_index_version("v2").status, IndexVersionStatus.READY)

    def test_duplicate_version_cannot_replace_retained_index(self) -> None:
        version = IndexVersion("v1", "model:8:l2:cosine", 1)
        self.repository.save_index_version(version)

        with self.assertRaisesRegex(ValueError, "already exists"):
            self.repository.save_index_version(version)

    def test_sqlite_and_postgres_adapters_share_the_contract(self) -> None:
        adapters = (
            SqliteMetadataRepository(":memory:"),
            PostgresMetadataRepository(sqlite3.connect(":memory:")),
        )
        for adapter in adapters:
            with self.subTest(adapter=type(adapter).__name__):
                value = {"device_id": "hw-01"}
                adapter.save_inventory("device-1", value)
                adapter.save_source("source-1", value)
                adapter.save_job("job-1", value)
                adapter.save_trace("trace-1", value)
                self.assertEqual(adapter.get_inventory("device-1"), value)
                self.assertEqual(adapter.get_source("source-1"), value)
                self.assertEqual(adapter.get_job("job-1"), value)
                self.assertEqual(adapter.get_trace("trace-1"), value)

                adapter.save_index_version(IndexVersion("v1", "model:8:l2:cosine", 1))
                adapter.save_index_version(IndexVersion("v2", "model:8:l2:cosine", 1))
                self.assertEqual(adapter.activate_alias("active", "v1").status, IndexVersionStatus.ACTIVE)
                self.assertEqual(adapter.activate_alias("active", "v2").version_id, "v2")
                self.assertEqual(adapter.rollback_alias("active", "v1").version_id, "v1")
                self.assertEqual(adapter.get_index_version("v2").status, IndexVersionStatus.READY)
                adapter.close()
