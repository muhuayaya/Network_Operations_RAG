"""使用注入集合客户端的 Chroma Dense 检索适配器。"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from netops_copilot.application.ports.indexing import DenseIndexPort, IndexableChunk
from netops_copilot.application.ports.models import EmbeddingPort, EmbeddingRequest
from netops_copilot.application.ports.search import (
    SearchCandidate,
    SearchChannel,
    SearchErrorCode,
    SearchFilters,
    SearchResult,
)


class ChromaDenseSearchAdapter:
    """将 Chroma Collection 查询转换为共享检索契约。"""

    def __init__(self, collection: Any) -> None:
        if not hasattr(collection, "query"):
            raise TypeError("Chroma collection must provide query()")
        self._collection = collection

    def search(
        self,
        query_vector: Sequence[float],
        filters: SearchFilters,
        limit: int = 10,
    ) -> SearchResult:
        if limit < 1 or not query_vector or any(not math.isfinite(value) for value in query_vector):
            return SearchResult.failed(SearchErrorCode.INVALID_REQUEST)
        try:
            response = self._collection.query(
                query_embeddings=[list(query_vector)],
                n_results=limit,
                where=dict(filters.as_mapping()) or None,
            )
            ids = _first_row(response.get("ids"))
            if not ids:
                return SearchResult.empty()
            distances = _first_row(response.get("distances"))
            metadatas = _first_row(response.get("metadatas"))
            documents = _first_row(response.get("documents"))
            candidates = []
            for index, chunk_id in enumerate(ids):
                metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
                distance = float(distances[index]) if index < len(distances) else 0.0
                candidates.append(
                    SearchCandidate(
                        chunk_id=str(chunk_id),
                        channel=SearchChannel.DENSE,
                        rank=index + 1,
                        raw_score=-distance,
                        metadata={str(key): str(value) for key, value in dict(metadata).items()},
                        text=str(documents[index]) if index < len(documents) else "",
                    )
                )
            return SearchResult.matches(candidates)
        except TimeoutError:
            return SearchResult.failed(SearchErrorCode.TIMEOUT)
        except (KeyError, TypeError, ValueError, IndexError):
            return SearchResult.failed(SearchErrorCode.UNKNOWN)
        except (OSError, RuntimeError):
            return SearchResult.failed(SearchErrorCode.UNAVAILABLE)


class ChromaDenseIndexWriter(DenseIndexPort):
    """通过模型端口为分块生成向量并写入持久化 Chroma。

    ``client`` is intentionally duck-typed.  Production code passes a
    ``chromadb.PersistentClient`` while tests can provide a tiny fake client.
    ``collection_name_factory`` must return the exact versioned collection name
    该写入器使用 :class:`VersionedIndexManager` 管理的版本化集合。
    """

    def __init__(
        self,
        client: Any,
        embedding: EmbeddingPort,
        *,
        collection_name_factory: Callable[[str], str] | None = None,
        # 百炼 text-embedding-v4 每次请求最多接受 10 个字符串。
        batch_size: int = 10,
    ) -> None:
        if not hasattr(client, "get_or_create_collection"):
            raise TypeError("Chroma client must provide get_or_create_collection()")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._client = client
        self._embedding = embedding
        self._collection_name_factory = collection_name_factory or (
            lambda version_id: f"netops_chunks__{_safe_identifier(version_id)}"
        )
        self._batch_size = batch_size

    def index_chunks(self, version_id: str, chunks: Sequence[IndexableChunk]) -> int:
        if not version_id.strip():
            raise ValueError("version_id cannot be blank")
        if not chunks:
            return 0
        collection = self._collection(version_id)
        accepted = 0
        for start in range(0, len(chunks), self._batch_size):
            batch = list(chunks[start : start + self._batch_size])
            result = self._embedding.embed(EmbeddingRequest(tuple(item.text for item in batch)))
            if result.status.value != "success":
                code = result.error_code.value if result.error_code is not None else "unknown"
                raise RuntimeError(f"Embedding 服务调用失败：{code}")
            if len(result.vectors) != len(batch):
                raise RuntimeError("embedding provider returned an unexpected vector count")
            values = {
                "ids": [item.chunk_id for item in batch],
                "documents": [item.text for item in batch],
                "embeddings": [list(vector) for vector in result.vectors],
                "metadatas": [dict(item.metadata) for item in batch],
            }
            # 使用 ``upsert``，调用方重用版本 ID 重试时不会产生重复记录。
            if hasattr(collection, "upsert"):
                collection.upsert(**values)
            else:
                collection.add(**values)
            accepted += len(batch)
        return accepted

    def count(self, version_id: str) -> int:
        return int(self._collection(version_id).count())

    def sample_readback(self, version_id: str, chunk_ids: Sequence[str]) -> bool:
        ids = [item for item in chunk_ids if item.strip()]
        if not ids:
            return False
        response = self._collection(version_id).get(ids=ids)
        actual = response.get("ids", []) if isinstance(response, Mapping) else []
        return {str(item) for item in actual} == set(ids)

    def collection(self, version_id: str) -> Any:
        """返回供查询服务组合使用的版本化集合。"""
        return self._collection(version_id)

    def _collection(self, version_id: str) -> Any:
        name = self._collection_name_factory(version_id)
        return self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )


def _first_row(value: Any) -> list[Any]:
    """读取 Chroma 的单查询嵌套响应，但不导入 Chroma。"""
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError("Chroma response field must be a nested sequence")
    if not value:
        return []
    row = value[0]
    if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
        raise TypeError("Chroma response row must be a sequence")
    return list(row)


def _safe_identifier(value: str) -> str:
    return "".join(character if character.isalnum() or character == "_" else "_" for character in value).strip("_")
