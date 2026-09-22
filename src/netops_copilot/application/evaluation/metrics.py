"""无额外依赖的排序、引用、分类和延迟指标。"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


def recall_at_k(expected: Iterable[str], predicted: Sequence[str], k: int) -> float:
    expected_set = set(expected)
    if not expected_set or k < 1:
        return 0.0
    return len(expected_set & set(predicted[:k])) / len(expected_set)


def mrr(expected: Iterable[str], predicted: Sequence[str]) -> float:
    expected_set = set(expected)
    for index, item in enumerate(predicted, start=1):
        if item in expected_set:
            return 1.0 / index
    return 0.0


def ndcg(expected: Iterable[str], predicted: Sequence[str], k: int) -> float:
    expected_set = set(expected)
    if not expected_set or k < 1:
        return 0.0
    gains = [1.0 if item in expected_set else 0.0 for item in predicted[:k]]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(k, len(expected_set))))
    return dcg / ideal if ideal else 0.0


def f1_score(expected: Iterable[str], predicted: Iterable[str]) -> float:
    expected_set, predicted_set = set(expected), set(predicted)
    if not expected_set and not predicted_set:
        return 1.0
    if not expected_set or not predicted_set:
        return 0.0
    true_positive = len(expected_set & predicted_set)
    precision = true_positive / len(predicted_set)
    recall = true_positive / len(expected_set)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def citation_precision(cited_ids: Iterable[str], evidence_ids: Iterable[str]) -> float:
    cited = list(cited_ids)
    if not cited:
        return 0.0
    evidence = set(evidence_ids)
    return sum(item in evidence for item in cited) / len(cited)


def citation_coverage(expected_ids: Iterable[str], cited_ids: Iterable[str]) -> float:
    expected = set(expected_ids)
    if not expected:
        return 1.0
    return len(expected & set(cited_ids)) / len(expected)


def refusal_accuracy(expected_refusal: bool, actual_refusal: bool) -> float:
    return float(expected_refusal == actual_refusal)


def diff_accuracy(expected_changes: Iterable[str], actual_changes: Iterable[str]) -> float:
    expected, actual = tuple(expected_changes), tuple(actual_changes)
    return float(expected == actual)


def latency_percentile(values: Sequence[float], percentile: float) -> float:
    if not values or not 0 <= percentile <= 100:
        raise ValueError("latency percentile requires values and 0..100 percentile")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil((percentile / 100) * len(ordered)) - 1))
    return float(ordered[index])


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    recall_at_k: float
    mrr: float
    ndcg: float
    citation_precision: float
    citation_coverage: float
    refusal_accuracy: float
    alarm_f1: float
    diff_accuracy: float
    p50_latency_ms: float
    p95_latency_ms: float


def regression_failures(
    current: EvaluationMetrics,
    baseline: EvaluationMetrics,
    *,
    relative_tolerance: float = 0.05,
) -> tuple[str, ...]:
    """返回低于认可基线或超过延迟预算的指标名称。"""
    if relative_tolerance < 0:
        raise ValueError("relative_tolerance cannot be negative")
    failures: list[str] = []
    for name in (
        "recall_at_k",
        "mrr",
        "ndcg",
        "citation_precision",
        "citation_coverage",
        "refusal_accuracy",
        "alarm_f1",
        "diff_accuracy",
    ):
        current_value = getattr(current, name)
        baseline_value = getattr(baseline, name)
        if current_value < baseline_value * (1 - relative_tolerance):
            failures.append(name)
    if current.p50_latency_ms > baseline.p50_latency_ms * (1 + relative_tolerance):
        failures.append("p50_latency_ms")
    if current.p95_latency_ms > baseline.p95_latency_ms * (1 + relative_tolerance):
        failures.append("p95_latency_ms")
    return tuple(failures)
