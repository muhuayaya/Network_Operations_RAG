"""demo-lite 运行时组合的离线测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from netops_copilot.application.demo_runtime import (
    build_demo_runtime,
    load_active_index_descriptor,
)
from netops_copilot.application.ports.models import EmbeddingRequest, EmbeddingResult, ModelStatus
from netops_copilot.settings import ProfileName


class _FakeEmbedding:
    def embed(self, request: EmbeddingRequest, timeout_seconds: float = 30.0) -> EmbeddingResult:
        vectors = tuple((float(len(text)), 1.0) for text in request.texts)
        return EmbeddingResult(ModelStatus.SUCCESS, vectors=vectors)


class _FakeCollection:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def upsert(self, **values: Any) -> None:
        for index, chunk_id in enumerate(values["ids"]):
            self.items[str(chunk_id)] = {
                "document": values["documents"][index],
                "embedding": values["embeddings"][index],
                "metadata": values["metadatas"][index],
            }

    add = upsert

    def count(self) -> int:
        return len(self.items)

    def get(self, ids: list[str], **_: Any) -> dict[str, list[str]]:
        return {"ids": [item for item in ids if item in self.items]}

    def query(self, **_: Any) -> dict[str, list[list[Any]]]:
        return {"ids": [[]], "distances": [[]], "metadatas": [[]]}


class _FakeChroma:
    def __init__(self) -> None:
        self.collections: dict[str, _FakeCollection] = {}

    def get_or_create_collection(self, name: str, **_: Any) -> _FakeCollection:
        return self.collections.setdefault(name, _FakeCollection())


class DemoRuntimeTests(unittest.TestCase):
    def test_build_registers_and_activates_both_indexes_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = build_demo_runtime(
                ProfileName.DEMO_LITE,
                Path("datasets/demo"),
                Path(directory),
                version_id="test-version",
                embedding=_FakeEmbedding(),
                chroma_client=_FakeChroma(),
            )
            self.assertEqual(report.version_id, "test-version")
            self.assertGreater(report.chunk_count, 0)
            self.assertEqual(report.chunk_count, report.dense_count)
            self.assertEqual(report.chunk_count, report.lexical_count)
            self.assertEqual(report.active_alias, "active")
            self.assertTrue((Path(directory) / "metadata.sqlite3").exists())
            active = load_active_index_descriptor(Path(directory))
            self.assertIsNotNone(active)
            self.assertEqual(active.collection_name, report.collection_name)


if __name__ == "__main__":
    unittest.main()
