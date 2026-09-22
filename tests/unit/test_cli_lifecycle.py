"""演示 CLI 生命周期确定性测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from netops_copilot.interfaces.cli.lifecycle import ingest_dataset, reset_runtime


class CliLifecycleTests(unittest.TestCase):
    def test_ingest_is_reproducible_and_reset_is_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset"
            runtime = root / "runtime"
            (dataset / "knowledge").mkdir(parents=True)
            (dataset / "knowledge" / "sop.md").write_text(
                "---\nsource_id: sop-1\nsource_type: sop\nsecurity_level: internal\n---\n\n# OSPF\nCheck ExStart.\n",
                encoding="utf-8",
            )
            first = ingest_dataset(dataset, runtime)
            manifest_first = json.loads((runtime / "ingestion_manifest.json").read_text(encoding="utf-8"))
            second = ingest_dataset(dataset, runtime)
            manifest_second = json.loads((runtime / "ingestion_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(first, second)
            self.assertEqual(manifest_first, manifest_second)
            reset_runtime(runtime)
            self.assertFalse(runtime.exists())
