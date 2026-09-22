"""Dense/Lexical 索引协调和激活检查。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from netops_copilot.application.indexing import ActiveIndex, VersionedIndexManager
from netops_copilot.application.ports.indexing import (
    DenseIndexPort,
    IndexableChunk,
    LexicalIndexPort,
)


class IndexingError(RuntimeError):
    """索引版本无法通过安全激活验证时抛出的异常。"""


@dataclass(frozen=True, slots=True)
class IndexBuildReport:
    """别名激活前记录的计数和样本证据。"""

    version_id: str
    expected_count: int
    dense_count: int
    lexical_count: int
    dense_sample_ok: bool
    lexical_sample_ok: bool
    active: ActiveIndex


class CoordinatedIndexer:
    """让部分存储成功的结果对活动查询不可见。"""

    def __init__(
        self,
        dense: DenseIndexPort,
        lexical: LexicalIndexPort,
        index_manager: VersionedIndexManager,
    ) -> None:
        self._dense = dense
        self._lexical = lexical
        self._index_manager = index_manager

    def index_and_activate(
        self,
        version_id: str,
        chunks: Sequence[IndexableChunk],
        *,
        sample_size: int = 3,
    ) -> IndexBuildReport:
        if not chunks:
            raise IndexingError("cannot activate an empty index version")
        if sample_size < 1:
            raise ValueError("sample_size must be positive")
        expected = len(chunks)
        chunk_ids = [chunk.chunk_id for chunk in chunks[:sample_size]]
        dense_written = self._dense.index_chunks(version_id, chunks)
        lexical_written = self._lexical.index_chunks(version_id, chunks)
        dense_count = self._dense.count(version_id)
        lexical_count = self._lexical.count(version_id)
        if dense_written != expected or lexical_written != expected:
            raise IndexingError("index writer accepted an unexpected chunk count")
        if dense_count != expected or lexical_count != expected:
            raise IndexingError("index count verification failed")
        dense_sample_ok = self._dense.sample_readback(version_id, chunk_ids)
        lexical_sample_ok = self._lexical.sample_readback(version_id, chunk_ids)
        if not dense_sample_ok or not lexical_sample_ok:
            raise IndexingError("index sample read-back verification failed")
        active = self._index_manager.activate(version_id)
        return IndexBuildReport(
            version_id,
            expected,
            dense_count,
            lexical_count,
            dense_sample_ok,
            lexical_sample_ok,
            active,
        )
