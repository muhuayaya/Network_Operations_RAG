"""可复现的评测数据、指标和回归检查。"""

from netops_copilot.application.evaluation.baseline import (
    BaselineReport,
    BaselineRunner,
    EvaluationVersion,
)
from netops_copilot.application.evaluation.golden import GoldenCase, load_golden_set
from netops_copilot.application.evaluation.metrics import (
    EvaluationMetrics,
    citation_coverage,
    citation_precision,
    diff_accuracy,
    f1_score,
    latency_percentile,
    mrr,
    ndcg,
    recall_at_k,
    refusal_accuracy,
    regression_failures,
)

__all__ = [
    "BaselineReport",
    "BaselineRunner",
    "EvaluationMetrics",
    "EvaluationVersion",
    "GoldenCase",
    "citation_coverage",
    "citation_precision",
    "diff_accuracy",
    "f1_score",
    "latency_percentile",
    "load_golden_set",
    "mrr",
    "ndcg",
    "recall_at_k",
    "refusal_accuracy",
    "regression_failures",
]
