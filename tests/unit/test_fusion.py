"""确定性倒数排名融合的 Golden Case 测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.fusion import FusionInputError, rrf_fuse
from netops_copilot.application.ports.search import (
    SearchCandidate,
    SearchChannel,
    SearchResult,
)


def _candidate(chunk_id: str, channel: SearchChannel, rank: int) -> SearchCandidate:
    return SearchCandidate(chunk_id, channel, rank, 1.0 / rank, {"source": channel.value})


class FusionTests(unittest.TestCase):
    def test_golden_order_and_channel_ranks_are_stable(self) -> None:
        dense = SearchResult.matches(
            [_candidate("chunk-a", SearchChannel.DENSE, 1), _candidate("chunk-b", SearchChannel.DENSE, 2)]
        )
        lexical = SearchResult.matches(
            [_candidate("chunk-b", SearchChannel.LEXICAL, 1), _candidate("chunk-c", SearchChannel.LEXICAL, 2)]
        )

        fused = rrf_fuse([dense, lexical], rrf_k=60, limit=3)

        self.assertEqual([candidate.chunk_id for candidate in fused], ["chunk-b", "chunk-a", "chunk-c"])
        self.assertEqual(
            fused[0].channel_ranks,
            ((SearchChannel.DENSE, 2), (SearchChannel.LEXICAL, 1)),
        )
        self.assertEqual(fused[0].metadata["source"], "dense")

    def test_ties_use_chunk_id_and_failed_channel_is_not_hidden(self) -> None:
        first = SearchResult.matches([_candidate("chunk-b", SearchChannel.DENSE, 1)])
        second = SearchResult.matches([_candidate("chunk-a", SearchChannel.LEXICAL, 1)])
        self.assertEqual([item.chunk_id for item in rrf_fuse([first, second])], ["chunk-a", "chunk-b"])
        with self.assertRaises(FusionInputError):
            rrf_fuse([SearchResult.failed("unavailable")])
