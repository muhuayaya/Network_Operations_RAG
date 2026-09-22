"""元数据仓储端口和版本化索引记录。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class RepositoryNotFoundError(LookupError):
    """请求的元数据记录不存在时抛出的异常。"""


class IndexVersionStatus(StrEnum):
    """持久化 Dense/Lexical 索引版本的生命周期状态。"""

    READY = "ready"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class IndexVersion:
    """激活或回滚索引版本所需的元数据。"""

    version_id: str
    embedding_fingerprint: str
    schema_version: int
    status: IndexVersionStatus = IndexVersionStatus.READY

    def __post_init__(self) -> None:
        if not self.version_id.strip() or not self.embedding_fingerprint.strip():
            raise ValueError("index version identifiers cannot be empty")
        if self.schema_version < 1:
            raise ValueError("index schema version must be positive")


class MetadataRepository(Protocol):
    """SQLite 和 PostgreSQL 适配器共享的存储契约。"""

    def save_inventory(self, entity_id: str, entity: Any) -> None:
        """创建或替换资产实体。"""

    def get_inventory(self, entity_id: str) -> Any:
        """读取资产实体。"""

    def save_source(self, source_id: str, source: Any) -> None:
        """创建或替换来源记录。"""

    def get_source(self, source_id: str) -> Any:
        """读取来源记录。"""

    def save_job(self, job_id: str, job: Any) -> None:
        """持久化摄取任务快照。"""

    def get_job(self, job_id: str) -> Any:
        """读取摄取任务快照。"""

    def save_trace(self, trace_id: str, trace: Any) -> None:
        """持久化查询 Trace。"""

    def get_trace(self, trace_id: str) -> Any:
        """读取查询 Trace。"""

    def save_index_version(self, version: IndexVersion) -> None:
        """注册尚未激活的索引版本。"""

    def get_index_version(self, version_id: str) -> IndexVersion:
        """读取索引版本记录。"""

    def activate_alias(self, alias: str, version_id: str) -> IndexVersion:
        """将活动别名指向已就绪的索引版本。"""

    def get_active_alias(self, alias: str) -> IndexVersion:
        """读取别名指向的活动版本。"""

    def rollback_alias(self, alias: str, version_id: str) -> IndexVersion:
        """将别名显式指回保留的索引版本。"""
