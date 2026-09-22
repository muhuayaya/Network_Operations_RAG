"""有边界观测的超时、错误和输出控制测试。"""

from __future__ import annotations

import time
import unittest

from netops_copilot.application.observation import (
    ObservationCoordinator,
    ObservationLimits,
    ObservationStatus,
)


class ObservationCoordinatorTests(unittest.TestCase):
    def test_timeout_and_error_never_fabricate_facts(self) -> None:
        def reader(target: str) -> object:
            if target == "slow":
                time.sleep(0.05)
                return {"fake": True}
            if target == "bad":
                raise RuntimeError("transport")
            return {"device": target}

        coordinator = ObservationCoordinator(ObservationLimits(timeout_seconds=0.001, max_output_chars=100))
        results, audits = coordinator.collect(["ok", "slow", "bad"], reader)
        self.assertEqual([item.status for item in results], [ObservationStatus.SUCCESS, ObservationStatus.TIMEOUT, ObservationStatus.ERROR])
        self.assertIsNone(results[1].facts)
        self.assertEqual(len(audits), 3)

    def test_output_limit_is_explicit_and_targets_are_bounded(self) -> None:
        coordinator = ObservationCoordinator(ObservationLimits(max_output_chars=5, max_targets=1))
        results, _ = coordinator.collect(["router-1"], lambda _: "this is too long")
        self.assertEqual(results[0].status, ObservationStatus.OUTPUT_LIMIT)
        with self.assertRaises(ValueError):
            coordinator.collect(["router-1", "router-2"], lambda _: {})
