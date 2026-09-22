"""Golden Set 和指标回归测试。"""

from __future__ import annotations

import unittest
from pathlib import Path

from netops_copilot.application.evaluation import (
    BaselineRunner,
    EvaluationMetrics,
    f1_score,
    latency_percentile,
    load_golden_set,
    mrr,
    ndcg,
    recall_at_k,
    regression_failures,
)


class EvaluationTests(unittest.TestCase):
    def test_demo_golden_set_has_scored_no_evidence_and_security_cases(self) -> None:
        path = Path(__file__).parents[2] / "datasets" / "demo" / "evals" / "golden_set.json"
        cases = load_golden_set(path)
        self.assertEqual(len(cases), 50)
        self.assertIn("security", {case.category for case in cases})
        self.assertEqual(sum(case.expected_behavior == "no_evidence" for case in cases), 7)
        self.assertEqual(sum(case.expected_behavior == "forbidden" for case in cases), 7)
        self.assertTrue(all(not case.expected_source_ids for case in cases if case.expected_behavior == "no_evidence"))
        self.assertTrue(all(case.principal_id for case in cases if case.expected_behavior == "forbidden"))

    def test_hand_calculated_ranking_and_latency_metrics(self) -> None:
        expected = ("a", "b")
        predicted = ("x", "a", "b")
        self.assertEqual(recall_at_k(expected, predicted, 2), 0.5)
        self.assertEqual(mrr(expected, predicted), 0.5)
        self.assertGreater(ndcg(expected, predicted, 3), 0.0)
        self.assertEqual(f1_score(("inc-1", "inc-2"), ("inc-2", "inc-3")), 0.5)
        self.assertEqual(latency_percentile((10.0, 20.0, 30.0, 40.0), 50), 20.0)

    def test_baseline_report_records_all_versions_and_regression_fails(self) -> None:
        report = BaselineRunner().run(
            profile="demo-lite",
            versions={"data": "demo-1", "model": "fake-1", "prompt": "prompt-1", "index": "idx-1", "code": "code-1"},
            execute=lambda mode: {"mode": mode},
            modes=("dense-only", "lexical-only", "hybrid", "hybrid-rerank"),
        )
        self.assertEqual(report.results["hybrid"]["mode"], "hybrid")
        baseline = EvaluationMetrics(1, 1, 1, 1, 1, 1, 1, 1, 100, 200)
        current = EvaluationMetrics(0.8, 1, 1, 1, 1, 1, 1, 1, 100, 220)
        self.assertIn("recall_at_k", regression_failures(current, baseline))
        self.assertIn("p95_latency_ms", regression_failures(current, baseline))


if __name__ == "__main__":
    unittest.main()
