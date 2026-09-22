"""元数据和索引持久化适配器。"""

from netops_copilot.infrastructure.persistence.memory import InMemoryMetadataRepository
from netops_copilot.infrastructure.persistence.postgres import PostgresMetadataRepository
from netops_copilot.infrastructure.persistence.sqlite import SqliteMetadataRepository

__all__ = [
    "InMemoryMetadataRepository",
    "PostgresMetadataRepository",
    "SqliteMetadataRepository",
]
