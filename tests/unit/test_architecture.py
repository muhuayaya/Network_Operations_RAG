"""架构依赖检查。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from check_architecture import find_violations


class ArchitectureCheckTests(unittest.TestCase):
    """确保受保护层不依赖框架和 SDK。"""

    def test_current_protected_layers_are_clean(self) -> None:
        package_root = Path(__file__).resolve().parents[2] / "src" / "netops_copilot"
        self.assertEqual(find_violations(package_root), [])

    def test_rejects_framework_and_sdk_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            for layer, statement in (
                ("domain", "import fastapi\n"),
                ("application", "from openai import OpenAI\n"),
            ):
                layer_path = package_root / layer
                layer_path.mkdir()
                (layer_path / "bad_dependency.py").write_text(statement, encoding="utf-8")

            violations = find_violations(package_root)

        self.assertEqual(len(violations), 2)
        self.assertTrue(any("fastapi" in violation for violation in violations))
        self.assertTrue(any("openai" in violation for violation in violations))
