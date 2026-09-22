"""稳定的来源类型切分测试。"""

from __future__ import annotations

import unittest

from netops_copilot.infrastructure.ingestion.chunking import chunk_record
from netops_copilot.infrastructure.ingestion.parsers import ParsedRecord, SourceLocation


class IngestionChunkingTests(unittest.TestCase):
    def _record(self, source_type: str, content: str) -> ParsedRecord:
        return ParsedRecord(
            "source-1",
            content,
            {"source_type": source_type, "site_id": "site-gz-dc"},
            SourceLocation("demo.txt", "text"),
            "source-hash",
        )

    def test_manual_reprocessing_produces_identical_ids_and_hashes(self) -> None:
        record = self._record("sop", "# OSPF\nNeighbor states\n\nCheck ExStart evidence.")
        first = chunk_record(record)
        second = chunk_record(record)
        self.assertEqual([(item.chunk_id, item.content_hash) for item in first], [(item.chunk_id, item.content_hash) for item in second])
        self.assertTrue(first[0].source_locator.endswith("#chunk:0"))

    def test_ticket_and_configuration_use_distinct_boundaries(self) -> None:
        ticket = chunk_record(self._record("ticket", "symptom\n\nroot cause\n\naction"))
        configuration = chunk_record(self._record("configuration", "interface Eth1\n description uplink\nrouter ospf 1\n area 0"))
        self.assertEqual(len(ticket), 3)
        self.assertEqual(len(configuration), 2)
