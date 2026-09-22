"""仓库资产策略测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from check_repository_assets import find_asset_policy_violations


class RepositoryAssetPolicyTests(unittest.TestCase):
    """拒绝复制的非产品材料，同时保留产品资产。"""

    def test_repository_currently_satisfies_the_asset_policy(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(find_asset_policy_violations(root), [])

    def test_rejects_representative_forbidden_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for relative_path in (
                "internal-guides/lesson.md",
                "docs/training-notes.md",
                "docs/personal-profile.md",
                "docs/question-bank.md",
                "docs/guide.pdf",
            ):
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder", encoding="utf-8")

            violations = find_asset_policy_violations(root)

        self.assertEqual(len(violations), 5)
