"""demo-lite Profile 使用的 SQLite FTS5/BM25 词法检索适配器。"""

from __future__ import annotations

import math
import re
import sqlite3
from collections.abc import Callable
from collections.abc import Sequence as SequenceABC
from pathlib import Path
from typing import Any

from netops_copilot.application.ports.indexing import IndexableChunk, LexicalIndexPort
from netops_copilot.application.ports.search import (
    SearchCandidate,
    SearchChannel,
    SearchErrorCode,
    SearchFilters,
    SearchResult,
)


class SqliteFts5SearchAdapter:
    """基于 FTS5 的词法检索，并支持参数化元数据过滤。"""

    def __init__(
        self,
        database: str | Path | sqlite3.Connection = ":memory:",
        *,
        table_name: str = "lexical_chunks",
    ) -> None:
        if isinstance(database, sqlite3.Connection):
            self._connection = database
            self._close_connection = False
        else:
            self._connection = sqlite3.connect(str(database))
            self._close_connection = True
        self._table_name = _safe_table_name(table_name)
        self._create_table(self._table_name)

    def _create_table(self, table_name: str) -> None:
        self._connection.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING fts5(
                chunk_id UNINDEXED,
                text,
                site_id UNINDEXED,
                device_id UNINDEXED,
                vendor UNINDEXED,
                os_version UNINDEXED,
                security_level UNINDEXED
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        if self._close_connection:
            self._connection.close()

    def upsert(
        self,
        chunk_id: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        if not chunk_id.strip() or not text.strip():
            raise ValueError("lexical chunks require non-empty identifiers and text")
        metadata = metadata or {}
        self._connection.execute(f"DELETE FROM {self._table_name} WHERE chunk_id=?", (chunk_id,))
        self._connection.execute(
            f"""
            INSERT INTO {self._table_name}(
                chunk_id, text, site_id, device_id, vendor, os_version, security_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                text,
                metadata.get("site_id", ""),
                metadata.get("device_id", ""),
                metadata.get("vendor", ""),
                metadata.get("os_version", ""),
                metadata.get("security_level", ""),
            ),
        )
        self._connection.commit()

    def search(
        self,
        query: str,
        filters: SearchFilters,
        limit: int = 10,
    ) -> SearchResult:
        if limit < 1 or not query.strip():
            return SearchResult.failed(SearchErrorCode.INVALID_REQUEST)
        terms = re.findall(r"\w+", query, flags=re.UNICODE)
        if not terms:
            return SearchResult.failed(SearchErrorCode.INVALID_REQUEST)
        expression = " OR ".join(f'"{term}"' for term in terms)
        try:
            conditions = [f"{self._table_name} MATCH ?"]
            parameters: list[Any] = [expression]
            for field, value in filters.as_mapping().items():
                conditions.append(f"{field}=?")
                parameters.append(value)
            parameters.append(limit)
            rows = self._connection.execute(
                f"SELECT chunk_id, text, bm25({self._table_name}), site_id, device_id, vendor, "
                f"os_version, security_level FROM {self._table_name} WHERE "
                + " AND ".join(conditions)
                + f" ORDER BY bm25({self._table_name}) LIMIT ?",
                tuple(parameters),
            ).fetchall()
        except sqlite3.OperationalError:
            return SearchResult.failed(SearchErrorCode.INVALID_REQUEST)
        except sqlite3.DatabaseError:
            return SearchResult.failed(SearchErrorCode.UNAVAILABLE)
        if not rows:
            return SearchResult.empty()
        candidates = []
        for rank, row in enumerate(rows, start=1):
            raw_score = -float(row[2])
            if not math.isfinite(raw_score):
                return SearchResult.failed(SearchErrorCode.UNKNOWN)
            candidates.append(
                SearchCandidate(
                    chunk_id=str(row[0]),
                    channel=SearchChannel.LEXICAL,
                    rank=rank,
                    raw_score=raw_score,
                    metadata={
                        "site_id": str(row[3]),
                        "device_id": str(row[4]),
                        "vendor": str(row[5]),
                        "os_version": str(row[6]),
                        "security_level": str(row[7]),
                    },
                    text=str(row[1]),
                )
            )
        return SearchResult.matches(candidates)


class SqliteFts5IndexWriter(LexicalIndexPort):
    """与 SQLite 元数据库共享存储的版本化 FTS5 写入器。"""

    def __init__(
        self,
        database: str | Path | sqlite3.Connection = ":memory:",
        *,
        table_name_factory: Callable[[str], str] | None = None,
    ) -> None:
        if isinstance(database, sqlite3.Connection):
            self._connection = database
            self._close_connection = False
        else:
            self._connection = sqlite3.connect(str(database))
            self._close_connection = True
        self._table_name_factory = table_name_factory or (
            lambda version_id: f"lexical_chunks__{_safe_table_name(version_id)}"
        )

    def close(self) -> None:
        if self._close_connection:
            self._connection.close()

    def index_chunks(self, version_id: str, chunks: SequenceABC[IndexableChunk]) -> int:
        table_name = self._table(version_id)
        self._create_table(table_name)
        for chunk in chunks:
            metadata = dict(chunk.metadata)
            self._connection.execute(
                f"DELETE FROM {table_name} WHERE chunk_id=?", (chunk.chunk_id,)
            )
            self._connection.execute(
                f"""INSERT INTO {table_name}(
                    chunk_id, text, site_id, device_id, vendor, os_version, security_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk.chunk_id,
                    chunk.text,
                    metadata.get("site_id", ""),
                    metadata.get("device_id", ""),
                    metadata.get("vendor", ""),
                    metadata.get("os_version", ""),
                    metadata.get("security_level", ""),
                ),
            )
        self._connection.commit()
        return len(chunks)

    def count(self, version_id: str) -> int:
        table_name = self._table(version_id)
        self._create_table(table_name)
        row = self._connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        return int(row[0]) if row is not None else 0

    def sample_readback(self, version_id: str, chunk_ids: SequenceABC[str]) -> bool:
        ids = [item for item in chunk_ids if item.strip()]
        if not ids:
            return False
        table_name = self._table(version_id)
        self._create_table(table_name)
        placeholders = ",".join("?" for _ in ids)
        rows = self._connection.execute(
            f"SELECT chunk_id FROM {table_name} WHERE chunk_id IN ({placeholders})", tuple(ids)
        ).fetchall()
        return {str(row[0]) for row in rows} == set(ids)

    def search_adapter(self, version_id: str) -> SqliteFts5SearchAdapter:
        """创建绑定到版本化 FTS5 表的检索适配器。"""
        return SqliteFts5SearchAdapter(self._connection, table_name=self._table(version_id))

    def _table(self, version_id: str) -> str:
        return _safe_table_name(self._table_name_factory(version_id))

    def _create_table(self, table_name: str) -> None:
        self._connection.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING fts5(
                chunk_id UNINDEXED,
                text,
                site_id UNINDEXED,
                device_id UNINDEXED,
                vendor UNINDEXED,
                os_version UNINDEXED,
                security_level UNINDEXED
            )
            """
        )
        self._connection.commit()


def _safe_table_name(value: str) -> str:
    candidate = "".join(character if character.isalnum() or character == "_" else "_" for character in value)
    candidate = candidate.strip("_")
    if not candidate or candidate[0].isdigit():
        candidate = f"t_{candidate}"
    return candidate
