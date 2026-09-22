"""Opt-in live local-milvus smoke test.

Run with ``RUN_LOCAL_MILVUS_INTEGRATION=1`` after Compose and the embedding
credential are configured. Without that explicit opt-in the test is skipped;
once opted in, service failures are test failures rather than skips.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from netops_copilot.application.local_milvus_runtime import (
    create_local_milvus_services,
    local_milvus_doctor,
)
from netops_copilot.settings import ProfileName


@unittest.skipUnless(
    os.environ.get("RUN_LOCAL_MILVUS_INTEGRATION") == "1",
    "set RUN_LOCAL_MILVUS_INTEGRATION=1 to run the live local-milvus smoke test",
)
class LocalMilvusLiveTests(unittest.TestCase):
    def test_ready_and_filtered_hybrid_query(self) -> None:
        report = local_milvus_doctor()
        self.assertEqual(report.status.value, "healthy")
        services = create_local_milvus_services(
            ProfileName.LOCAL_MILVUS,
            Path("datasets/demo/.runtime"),
        )
        result = services.query(
            {"query": "OSPF ExStart", "vendor": "H3C", "mode": "hybrid", "limit": 5}
        )
        self.assertEqual(result["state"], "healthy")
        self.assertTrue(result["candidates"])
        self.assertTrue(all(item["metadata"].get("vendor") == "H3C" for item in result["candidates"]))
