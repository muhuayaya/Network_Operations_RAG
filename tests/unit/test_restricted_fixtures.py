"""验证受限演示证据包含两种授权结果。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from netops_copilot.domain.shared import Principal, SecurityLevel


class RestrictedFixtureTests(unittest.TestCase):
    """普通和受限主体共同测试 site-gz 访问边界。"""

    def test_three_restricted_site_gz_fixtures_and_two_principals_exist(self) -> None:
        root = Path(__file__).resolve().parents[2] / "datasets" / "demo"
        principals = json.loads((root / "access" / "principals.json").read_text(encoding="utf-8"))
        restricted_documents = []
        for path in (root / "knowledge").glob("doc-sop-restricted-gz-*.md"):
            text = path.read_text(encoding="utf-8")
            if 'site_id: "site-gz-dc"' in text and 'security_level: "restricted"' in text:
                restricted_documents.append(path)

        self.assertEqual(len(principals), 2)
        self.assertEqual(len(restricted_documents), 3)
        basic = Principal("principal-basic-demo", SecurityLevel.BASIC, frozenset({"site-gz-dc"}))
        restricted = Principal(
            "principal-restricted-demo", SecurityLevel.RESTRICTED, frozenset({"site-gz-dc"})
        )
        self.assertFalse(basic.can_access("site-gz-dc", SecurityLevel.RESTRICTED))
        self.assertTrue(restricted.can_access("site-gz-dc", SecurityLevel.RESTRICTED))
