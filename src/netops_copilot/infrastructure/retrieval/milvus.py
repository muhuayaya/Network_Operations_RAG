"""位于共享检索端口之后的 Milvus Dense 和稀疏/BM25 适配器。"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from netops_copilot.application.ports.indexing import (
    DenseIndexPort,
    IndexableChunk,
    LexicalIndexPort,
)
from netops_copilot.application.ports.models import EmbeddingPort, EmbeddingRequest
from netops_copilot.application.ports.search import (
    SearchCandidate,
    SearchChannel,
    SearchErrorCode,
    SearchFilters,
    SearchResult,
)


@dataclass(frozen=True, slots=True)
class MilvusHealthReport:
    """索引集合的安全健康和结构检查结果。"""

    healthy: bool
    collection_name: str
    schema_fields: tuple[str, ...] = ()
    reason: str | None = None


def build_milvus_filter(filters: SearchFilters) -> str:
    """根据已授权过滤条件构建允许列表内的标量表达式。"""
    return " and ".join(
        f"{field} == {json.dumps(value)}" for field, value in filters.as_mapping().items()
    )


class _MilvusSearchBase:
    def __init__(
        self,
        collection: Any,
        *,
        anns_field: str,
        collection_name: str | None = None,
        search_params: Mapping[str, Any] | None = None,
    ) -> None:
        if not hasattr(collection, "search"):
            raise TypeError("Milvus collection must provide search()")
        self._collection = collection
        self._anns_field = anns_field
        self._collection_name = collection_name or str(getattr(collection, "name", "unknown"))
        self._search_params = dict(search_params or {})

    def health_check(self, expected_fields: Sequence[str] = ()) -> MilvusHealthReport:
        schema = getattr(self._collection, "schema", None)
        if schema is None:
            return MilvusHealthReport(False, self._collection_name, reason="schema unavailable")
        fields = tuple(_field_name(field) for field in getattr(schema, "fields", ()))
        missing = sorted(set(expected_fields) - set(fields))
        if missing:
            return MilvusHealthReport(
                False,
                self._collection_name,
                fields,
                reason=f"missing schema fields: {', '.join(missing)}",
            )
        return MilvusHealthReport(True, self._collection_name, fields)

    def _search_hits(self, data: list[Any], filters: SearchFilters, limit: int) -> SearchResult:
        if limit < 1:
            return SearchResult.failed(SearchErrorCode.INVALID_REQUEST)
        try:
            response = self._collection.search(
                data=data,
                anns_field=self._anns_field,
                param=self._search_params,
                limit=limit,
                expr=build_milvus_filter(filters),
                output_fields=[
                    "chunk_id",
                    "text",
                    "site_id",
                    "device_id",
                    "vendor",
                    "os_version",
                    "security_level",
                ],
            )
            hits = _first_row(response)
            if not hits:
                return SearchResult.empty()
            return self._map_hits(hits)
        except TimeoutError:
            return SearchResult.failed(SearchErrorCode.TIMEOUT)
        except (KeyError, TypeError, ValueError, IndexError):
            return SearchResult.failed(SearchErrorCode.UNKNOWN)
        except (OSError, RuntimeError):
            return SearchResult.failed(SearchErrorCode.UNAVAILABLE)

    def _map_hits(self, hits: Sequence[Any]) -> SearchResult:
        raise NotImplementedError


class MilvusDenseSearchAdapter(_MilvusSearchBase):
    """Milvus 向量检索适配器。"""

    def search(self, query_vector: Sequence[float], filters: SearchFilters, limit: int = 10) -> SearchResult:
        if not query_vector or any(not math.isfinite(value) for value in query_vector):
            return SearchResult.failed(SearchErrorCode.INVALID_REQUEST)
        return self._search_hits([list(query_vector)], filters, limit)

    def _map_hits(self, hits: Sequence[Any]) -> SearchResult:
        return _map_hits(hits, SearchChannel.DENSE, score_transform=lambda value: -value)


class MilvusSparseBm25SearchAdapter(_MilvusSearchBase):
    """接收已配置稀疏查询编码器输入的 Milvus 稀疏/BM25 适配器。"""

    def search(self, query: str, filters: SearchFilters, limit: int = 10) -> SearchResult:
        if not query.strip():
            return SearchResult.failed(SearchErrorCode.INVALID_REQUEST)
        return self._search_hits([query], filters, limit)

    def _map_hits(self, hits: Sequence[Any]) -> SearchResult:
        return _map_hits(hits, SearchChannel.LEXICAL, score_transform=lambda value: value)


class MilvusDenseIndexWriter(DenseIndexPort):
    """Write dense vectors and BM25 source text to one Milvus collection."""

    def __init__(
        self,
        collection: Any,
        embedding: EmbeddingPort,
        *,
        dimension: int,
        batch_size: int = 10,
    ) -> None:
        if not hasattr(collection, "upsert"):
            raise TypeError("Milvus collection must provide upsert()")
        if dimension < 1 or batch_size < 1:
            raise ValueError("dimension and batch_size must be positive")
        self._collection = collection
        self._embedding = embedding
        self._dimension = dimension
        self._batch_size = batch_size

    def index_chunks(self, version_id: str, chunks: Sequence[IndexableChunk]) -> int:
        if not version_id.strip():
            raise ValueError("version_id cannot be blank")
        accepted = 0
        for start in range(0, len(chunks), self._batch_size):
            batch = list(chunks[start : start + self._batch_size])
            result = self._embedding.embed(EmbeddingRequest(tuple(item.text for item in batch)))
            if result.status.value != "success":
                code = result.error_code.value if result.error_code is not None else "unknown"
                raise RuntimeError(f"Embedding 服务调用失败：{code}")
            if len(result.vectors) != len(batch):
                raise RuntimeError("embedding provider returned an unexpected vector count")
            data: list[dict[str, Any]] = []
            for item, vector in zip(batch, result.vectors, strict=True):
                if len(vector) != self._dimension or any(not math.isfinite(value) for value in vector):
                    raise ValueError("embedding vector dimension or values are invalid")
                entity: dict[str, Any] = {
                    "chunk_id": item.chunk_id,
                    "text": item.text,
                    "embedding": list(vector),
                }
                for field in ("site_id", "device_id", "vendor", "os_version", "security_level", "source_id", "source_locator", "content_hash"):
                    if field in item.metadata:
                        entity[field] = str(item.metadata[field])
                data.append(entity)
            self._collection.upsert(data=data)
            accepted += len(batch)
        if hasattr(self._collection, "flush"):
            self._collection.flush()
        if hasattr(self._collection, "load"):
            self._collection.load()
        return accepted

    def count(self, version_id: str) -> int:
        return int(self._collection.count())

    def sample_readback(self, version_id: str, chunk_ids: Sequence[str]) -> bool:
        ids = [item for item in chunk_ids if item.strip()]
        if not ids:
            return False
        response = self._collection.get(ids=ids)
        actual = response.get("ids", []) if isinstance(response, Mapping) else []
        return {str(item) for item in actual} == set(ids)


class MilvusSparseBm25IndexWriter(LexicalIndexPort):
    """Validate Milvus' built-in BM25 materialization for a version collection."""

    def __init__(self, collection: Any) -> None:
        if not hasattr(collection, "count"):
            raise TypeError("Milvus collection must provide count()")
        self._collection = collection

    def index_chunks(self, version_id: str, chunks: Sequence[IndexableChunk]) -> int:
        if not version_id.strip():
            raise ValueError("version_id cannot be blank")
        # The dense writer inserts the raw text; the collection's BM25 Function
        # generates the sparse field server-side for the same entities.
        if hasattr(self._collection, "load"):
            self._collection.load()
        return len(chunks) if self.count(version_id) == len(chunks) else 0

    def count(self, version_id: str) -> int:
        return int(self._collection.count())

    def sample_readback(self, version_id: str, chunk_ids: Sequence[str]) -> bool:
        ids = [item for item in chunk_ids if item.strip()]
        if not ids:
            return False
        response = self._collection.get(ids=ids)
        actual = response.get("ids", []) if isinstance(response, Mapping) else []
        return {str(item) for item in actual} == set(ids)


def _first_row(response: Any) -> list[Any]:
    if response is None:
        return []
    if isinstance(response, Sequence) and response and isinstance(response[0], Sequence):
        return list(response[0])
    if isinstance(response, Sequence):
        return list(response)
    raise TypeError("Milvus search response must be a sequence")


def _field_name(field: Any) -> str:
    if isinstance(field, Mapping):
        return str(field.get("name", ""))
    return str(getattr(field, "name", field))


def _map_hits(
    hits: Sequence[Any],
    channel: SearchChannel,
    *,
    score_transform: Any,
) -> SearchResult:
    candidates = []
    for rank, hit in enumerate(hits, start=1):
        identifier, score, metadata, text = _hit_values(hit)
        raw_score = float(score_transform(float(score)))
        if not math.isfinite(raw_score):
            return SearchResult.failed(SearchErrorCode.UNKNOWN)
        candidates.append(
            SearchCandidate(
                chunk_id=identifier,
                channel=channel,
                rank=rank,
                raw_score=raw_score,
                metadata=metadata,
                text=text,
            )
        )
    return SearchResult.matches(candidates) if candidates else SearchResult.empty()


def _hit_values(hit: Any) -> tuple[str, float, dict[str, str], str]:
    if isinstance(hit, Mapping):
        identifier = hit.get("id", hit.get("pk", hit.get("chunk_id")))
        score = hit.get("distance", hit.get("score", 0.0))
        metadata = hit.get("entity", hit.get("metadata", {}))
    else:
        identifier = getattr(hit, "id", getattr(hit, "pk", getattr(hit, "chunk_id", None)))
        score = getattr(hit, "distance", getattr(hit, "score", 0.0))
        metadata = getattr(hit, "entity", getattr(hit, "metadata", {}))
    if identifier is None:
        raise KeyError("Milvus hit has no identifier")
    if not isinstance(metadata, Mapping):
        metadata = {}
    normalized = {str(key): str(value) for key, value in metadata.items()}
    text = normalized.pop("text", "")
    return str(identifier), float(score), normalized, text
