"""协调激活服务使用的索引写入端口。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class IndexableChunk:
    """发送给 Dense/Lexical 写入器的最小后端无关载荷。"""

    chunk_id: str
    text: str
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.chunk_id.strip() or not self.text.strip():
            raise ValueError("indexable chunks require an id and text")


class DenseIndexPort(Protocol):
    """写入并验证一个 Dense 索引版本。"""

    def index_chunks(self, version_id: str, chunks: Sequence[IndexableChunk]) -> int:
        """返回后端接受的分块数量。"""

    def count(self, version_id: str) -> int:
        """返回某个版本已持久化的分块数量。"""

    def sample_readback(self, version_id: str, chunk_ids: Sequence[str]) -> bool:
        """确认代表性 ID 可以被读回。"""


class LexicalIndexPort(Protocol):
    """写入并验证一个 Lexical 索引版本。"""

    def index_chunks(self, version_id: str, chunks: Sequence[IndexableChunk]) -> int:
        """返回后端接受的分块数量。"""

    def count(self, version_id: str) -> int:
        """返回某个版本已持久化的分块数量。"""

    def sample_readback(self, version_id: str, chunk_ids: Sequence[str]) -> bool:
        """确认代表性 ID 可以被读回。"""
