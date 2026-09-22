"""供测试和 test Profile 使用的确定性内存元数据仓储。"""

from __future__ import annotations

from typing import Any, cast

from netops_copilot.application.ports.repositories import (
    IndexVersion,
    IndexVersionStatus,
    RepositoryNotFoundError,
)


class InMemoryMetadataRepository:
    """支持显式别名激活和回滚的仓储实现。"""

    def __init__(self) -> None:
        self._inventory: dict[str, Any] = {}
        self._sources: dict[str, Any] = {}
        self._jobs: dict[str, Any] = {}
        self._traces: dict[str, Any] = {}
        self._versions: dict[str, IndexVersion] = {}
        self._aliases: dict[str, str] = {}

    def _save(self, collection: dict[str, Any], record_id: str, record: Any) -> None:
        if not record_id.strip():
            raise ValueError("metadata record id cannot be empty")
        collection[record_id] = record

    def _get(self, collection: dict[str, Any], record_id: str) -> Any:
        try:
            return collection[record_id]
        except KeyError as error:
            raise RepositoryNotFoundError(record_id) from error

    def save_inventory(self, entity_id: str, entity: Any) -> None:
        self._save(self._inventory, entity_id, entity)

    def get_inventory(self, entity_id: str) -> Any:
        return self._get(self._inventory, entity_id)

    def save_source(self, source_id: str, source: Any) -> None:
        self._save(self._sources, source_id, source)

    def get_source(self, source_id: str) -> Any:
        return self._get(self._sources, source_id)

    def save_job(self, job_id: str, job: Any) -> None:
        self._save(self._jobs, job_id, job)

    def get_job(self, job_id: str) -> Any:
        return self._get(self._jobs, job_id)

    def save_trace(self, trace_id: str, trace: Any) -> None:
        self._save(self._traces, trace_id, trace)

    def get_trace(self, trace_id: str) -> Any:
        return self._get(self._traces, trace_id)

    def save_index_version(self, version: IndexVersion) -> None:
        if version.version_id in self._versions:
            raise ValueError(f"index version already exists: {version.version_id}")
        self._versions[version.version_id] = version

    def get_index_version(self, version_id: str) -> IndexVersion:
        return cast(IndexVersion, self._get(self._versions, version_id))

    def activate_alias(self, alias: str, version_id: str) -> IndexVersion:
        version = self.get_index_version(version_id)
        if version.status not in {IndexVersionStatus.READY, IndexVersionStatus.ACTIVE}:
            raise ValueError(f"index version cannot be activated: {version_id}")
        current_id = self._aliases.get(alias)
        if current_id is not None:
            current = self._versions[current_id]
            self._versions[current_id] = IndexVersion(
                current.version_id,
                current.embedding_fingerprint,
                current.schema_version,
                IndexVersionStatus.READY,
            )
        active = IndexVersion(
            version.version_id,
            version.embedding_fingerprint,
            version.schema_version,
            IndexVersionStatus.ACTIVE,
        )
        self._versions[version_id] = active
        self._aliases[alias] = version_id
        return active

    def get_active_alias(self, alias: str) -> IndexVersion:
        try:
            version_id = self._aliases[alias]
        except KeyError as error:
            raise RepositoryNotFoundError(alias) from error
        return self.get_index_version(version_id)

    def rollback_alias(self, alias: str, version_id: str) -> IndexVersion:
        if alias not in self._aliases:
            raise RepositoryNotFoundError(alias)
        return self.activate_alias(alias, version_id)
