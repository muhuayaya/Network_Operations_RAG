"""应用层的确定性倒数排名融合。"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from netops_copilot.application.ports.search import (
    SearchCandidate,
    SearchChannel,
    SearchResult,
    SearchStatus,
)


class FusionInputError(ValueError):
    """通道失败无法安全静默融合时抛出的异常。"""


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    """带有确定性通道和排名来源的融合候选项。"""

    chunk_id: str
    fused_score: float
    channel_ranks: tuple[tuple[SearchChannel, int], ...]
    source_candidates: tuple[SearchCandidate, ...]
    metadata: Mapping[str, str]
    text: str = ""

    def __post_init__(self) -> None:
        if not self.chunk_id.strip() or not self.source_candidates:
            raise ValueError("fused candidates require an id and source provenance")
        if not math.isfinite(self.fused_score):
            raise ValueError("fused score must be finite")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def rrf_fuse(
    results: Iterable[SearchResult],
    *,
    rrf_k: int = 60,
    limit: int = 10,
) -> tuple[FusedCandidate, ...]:
    """使用 RRF 融合通道结果，并按稳定分数和 ID 排序。"""
    if rrf_k < 1 or limit < 1:
        raise ValueError("rrf_k and limit must be positive")
    grouped: dict[str, list[SearchCandidate]] = defaultdict(list)
    for result in results:
        if result.status is SearchStatus.FAILED:
            raise FusionInputError(f"cannot fuse failed search result: {result.error_code}")
        grouped_candidates = result.candidates if result.status is SearchStatus.MATCHES else ()
        for candidate in grouped_candidates:
            grouped[candidate.chunk_id].append(candidate)

    fused: list[FusedCandidate] = []
    for chunk_id, source_candidates in grouped.items():
        deduplicated = _best_channel_candidates(source_candidates)
        score = sum(1.0 / (rrf_k + candidate.rank) for candidate in deduplicated)
        ordered_sources = tuple(sorted(deduplicated, key=lambda item: (item.channel.value, item.rank)))
        channel_ranks = tuple((candidate.channel, candidate.rank) for candidate in ordered_sources)
        metadata = ordered_sources[0].metadata
        text = next((candidate.text for candidate in ordered_sources if candidate.text), "")
        fused.append(FusedCandidate(chunk_id, score, channel_ranks, ordered_sources, metadata, text))
    fused.sort(key=lambda item: (-item.fused_score, item.chunk_id))
    return tuple(fused[:limit])


def _best_channel_candidates(candidates: list[SearchCandidate]) -> tuple[SearchCandidate, ...]:
    best: dict[SearchChannel, SearchCandidate] = {}
    for candidate in candidates:
        current = best.get(candidate.channel)
        if current is None or candidate.rank < current.rank:
            best[candidate.channel] = candidate
    return tuple(best.values())
