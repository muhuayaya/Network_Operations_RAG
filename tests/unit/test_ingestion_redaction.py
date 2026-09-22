"""索引前秘密检测和安全掩码测试。"""

from __future__ import annotations

import unittest

from netops_copilot.infrastructure.ingestion.parsers import ParsedRecord, SourceLocation
from netops_copilot.infrastructure.ingestion.redaction import (
    RedactionPolicy,
    SensitiveAction,
    SensitiveDataError,
    protect_record,
)


class IngestionRedactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.record = ParsedRecord(
            source_id="config-1",
            content="username ops password=super-secret\ninterface Eth1",
            metadata={"site_id": "site-gz-dc"},
            location=SourceLocation("config.cfg", "line:1"),
            content_hash="old",
        )

    def test_default_policy_rejects_secret_without_echoing_value(self) -> None:
        with self.assertRaises(SensitiveDataError) as context:
            protect_record(self.record)
        self.assertIn("password", str(context.exception))
        self.assertNotIn("super-secret", str(context.exception))

    def test_mask_policy_removes_secret_before_indexing(self) -> None:
        masked = protect_record(self.record, RedactionPolicy(SensitiveAction.MASK))
        self.assertNotIn("super-secret", masked.content)
        self.assertIn("[REDACTED]", masked.content)
        self.assertNotEqual(masked.content_hash, "old")

    def test_metadata_secrets_are_also_rejected(self) -> None:
        record = ParsedRecord(
            self.record.source_id,
            "safe text",
            {"api_key": "api-key=super-secret"},
            self.record.location,
            self.record.content_hash,
        )
        with self.assertRaises(SensitiveDataError):
            protect_record(record)
