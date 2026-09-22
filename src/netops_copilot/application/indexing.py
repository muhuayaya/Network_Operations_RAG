"""Embedding 指纹索引命名和活动别名生命周期。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from netops_copilot.application.ports.repositories import IndexVersion, MetadataRepository


class IndexCompatibilityError(ValueError):
    """查询将使用其他 Embedding 空间索引时抛出的异常。"""


def collection_name(base_name: str, embedding_fingerprint: str, version_id: str) -> str:
    """构建确定性且适合存储的集合名称。"""
    parts = (base_name, embedding_fingerprint, version_id)
    if any(not part.strip() for part in parts):
        raise ValueError("collection name parts cannot be blank")
    value = "__".join(_safe_name(part) for part in parts)
    # Chroma 和 Milvus 都限制标识符最多 63 个字符。
    # 短名称保持可读，较长的指纹和版本 ID 则使用稳定摘要。
    if len(value) > 63:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
        value = f"{value[:54]}_{digest}"
    return value


@dataclass(frozen=True, slots=True)
class ActiveIndex:
    """供查询适配器使用的已解析别名绑定。"""

    alias: str
    version: IndexVersion
    collection_name: str


class VersionedIndexManager:
    """协调索引注册、激活、回滚和查询保护。"""

    def __init__(
        self,
        repository: MetadataRepository,
        *,
        alias: str = "active",
        base_name: str = "netops_chunks",
    ) -> None:
        if not alias.strip() or not base_name.strip():
            raise ValueError("index alias and base name cannot be blank")
        self._repository = repository
        self._alias = alias
        self._base_name = base_name

    def register(self, version: IndexVersion) -> str:
        self._repository.save_index_version(version)
        return collection_name(self._base_name, version.embedding_fingerprint, version.version_id)

    def activate(self, version_id: str) -> ActiveIndex:
        version = self._repository.activate_alias(self._alias, version_id)
        return self._binding(version)

    def rollback(self, version_id: str) -> ActiveIndex:
        version = self._repository.rollback_alias(self._alias, version_id)
        return self._binding(version)

    def active(self) -> ActiveIndex:
        return self._binding(self._repository.get_active_alias(self._alias))

    def assert_query_compatible(
        self,
        *,
        collection: str,
        embedding_fingerprint: str,
        schema_version: int,
    ) -> ActiveIndex:
        active = self.active()
        if active.collection_name != collection:
            raise IndexCompatibilityError("collection is not the active alias target")
        if active.version.embedding_fingerprint != embedding_fingerprint:
            raise IndexCompatibilityError("embedding fingerprint is incompatible with active index")
        if active.version.schema_version != schema_version:
            raise IndexCompatibilityError("index schema version is incompatible")
        return active

    def _binding(self, version: IndexVersion) -> ActiveIndex:
        return ActiveIndex(
            alias=self._alias,
            version=version,
            collection_name=collection_name(
                self._base_name,
                version.embedding_fingerprint,
                version.version_id,
            ),
        )


def _safe_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    if not sanitized:
        raise ValueError("collection name part has no safe characters")
    return sanitized
