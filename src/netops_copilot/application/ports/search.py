"""与后端无关的检索 DTO 和 Dense/Lexical 检索端口。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol


class SearchChannel(StrEnum):
    """产生候选结果的检索通道。"""

    DENSE = "dense"
    LEXICAL = "lexical"


class SearchStatus(StrEnum):
    """区分没有匹配和后端失败的结果状态。"""

    MATCHES = "matches"
    EMPTY = "empty"
    FAILED = "failed"


class SearchErrorCode(StrEnum):
    """安全且稳定的检索失败类别。"""

    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    INVALID_REQUEST = "invalid_request"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """所有检索后端共享的已授权元数据约束。"""

    site_id: str | None = None
    device_id: str | None = None
    vendor: str | None = None
    os_version: str | None = None
    security_level: str | None = None

    def __post_init__(self) -> None:
        for name in ("site_id", "device_id", "vendor", "os_version", "security_level"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} filter cannot be blank")

    def as_mapping(self) -> Mapping[str, str]:
        """只返回当前生效的约束，供后端转换使用。"""
        return MappingProxyType(
            {
                name: value
                for name in ("site_id", "device_id", "vendor", "os_version", "security_level")
                if (value := getattr(self, name)) is not None
            }
        )


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    """保留通道来源、与后端无关的排序候选结果。"""

    chunk_id: str
    channel: SearchChannel
    rank: int
    raw_score: float
    metadata: Mapping[str, str]
    text: str = ""

    def __post_init__(self) -> None:
        if not self.chunk_id.strip():
            raise ValueError("search candidate chunk_id cannot be empty")
        if self.rank < 1:
            raise ValueError("search candidate rank must be positive")
        if not math.isfinite(self.raw_score):
            raise ValueError("search candidate score must be finite")
        if not isinstance(self.text, str):
            raise TypeError("search candidate text must be a string")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class SearchResult:
    """类型化检索响应，不混淆空结果和失败。"""

    status: SearchStatus
    candidates: tuple[SearchCandidate, ...] = ()
    error_code: SearchErrorCode | None = None

    def __post_init__(self) -> None:
        if self.status is SearchStatus.MATCHES and not self.candidates:
            raise ValueError("matches result requires candidates")
        if self.status is SearchStatus.EMPTY and self.candidates:
            raise ValueError("empty result cannot contain candidates")
        if self.status is SearchStatus.FAILED and self.error_code is None:
            raise ValueError("failed result requires an error code")
        if self.status is not SearchStatus.FAILED and self.error_code is not None:
            raise ValueError("only failed results may contain an error code")

    @classmethod
    def matches(cls, candidates: Sequence[SearchCandidate]) -> SearchResult:
        return cls(SearchStatus.MATCHES, tuple(candidates))

    @classmethod
    def empty(cls) -> SearchResult:
        return cls(SearchStatus.EMPTY)

    @classmethod
    def failed(cls, error_code: SearchErrorCode) -> SearchResult:
        return cls(SearchStatus.FAILED, error_code=error_code)


class DenseSearchPort(Protocol):
    """向量相似度检索端口。"""

    def search(
        self,
        query_vector: Sequence[float],
        filters: SearchFilters,
        limit: int = 10,
    ) -> SearchResult:
        """返回 Dense 候选、明确的空结果或失败。"""


class LexicalSearchPort(Protocol):
    """词法/BM25 检索端口。"""

    def search(
        self,
        query: str,
        filters: SearchFilters,
        limit: int = 10,
    ) -> SearchResult:
        """返回 Lexical 候选、明确的空结果或失败。"""
