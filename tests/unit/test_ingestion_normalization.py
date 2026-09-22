"""厂商和元数据规范化固定数据测试。"""

from __future__ import annotations

import unittest

from netops_copilot.domain.inventory import OsFamily, Vendor
from netops_copilot.infrastructure.ingestion.normalization import normalize_record
from netops_copilot.infrastructure.ingestion.parsers import ParsedRecord, SourceLocation


class IngestionNormalizationTests(unittest.TestCase):
    def test_four_vendor_fixtures_map_to_canonical_os_families(self) -> None:
        fixtures = (
            ("Huawei", "VRP", Vendor.HUAWEI, OsFamily.VRP),
            ("H3C", "Comware", Vendor.H3C, OsFamily.COMWARE),
            ("Ruijie", "RGOS", Vendor.RUIJIE, OsFamily.RGOS),
            ("Cisco-compatible", "IOS", Vendor.CISCO, OsFamily.IOS),
        )
        for vendor, os_family, expected_vendor, expected_os in fixtures:
            with self.subTest(vendor=vendor):
                record = ParsedRecord(
                    source_id=f"{vendor}-1",
                    content="show interface",
                    metadata={
                        "source_type": "vendor_reference",
                        "vendor": vendor,
                        "os_family": os_family,
                        "model": "demo",
                        "os_version": "1.0",
                        "site_id": "site-gz-dc",
                        "security_level": "internal",
                        "effective_at": "2026-09-01",
                    },
                    location=SourceLocation("fixture.md", "text"),
                    content_hash="hash",
                )
                normalized = normalize_record(record)
                self.assertEqual(normalized.vendor, expected_vendor)
                self.assertEqual(normalized.os_family, expected_os)
                self.assertEqual(normalized.metadata["source_type"], "manual")

    def test_missing_effective_time_is_deterministic_and_bad_alias_fails(self) -> None:
        record = ParsedRecord("source", "facts", {}, SourceLocation("x.txt", "text"), "hash")
        self.assertEqual(normalize_record(record).effective_at.year, 1970)
        bad = ParsedRecord(
            "source",
            "facts",
            {"vendor": "unknown"},
            SourceLocation("x.txt", "text"),
            "hash",
        )
        with self.assertRaisesRegex(ValueError, "vendor alias"):
            normalize_record(bad)
