"""失败分类和已配置的降级状态。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from netops_copilot.application.ports.models import LLMResult, ModelStatus
from netops_copilot.application.ports.search import SearchResult, SearchStatus


class DegradationState(StrEnum):
    """面向用户显示的查询可用状态。"""

    HEALTHY = "healthy"
    ZERO_EVIDENCE = "zero-evidence"
    PARTIAL = "partial-degradation"
    TOTAL_UNAVAILABLE = "total-unavailable"


@dataclass(frozen=True, slots=True)
class FailureClassification:
    """供 Trace 和响应使用的安全通道/错误分类。"""

    state: DegradationState
    failures: tuple[str, ...] = ()


def classify_query(
    dense: SearchResult | None,
    lexical: SearchResult | None,
    llm: LLMResult | None = None,
) -> FailureClassification:
    """区分没有证据与后端或 provider 不可用。"""
    retrieval = [result for result in (dense, lexical) if result is not None]
    failures = [
        f"{channel}:{result.error_code}"
        for channel, result in (("dense", dense), ("lexical", lexical))
        if result is not None and result.status is SearchStatus.FAILED
    ]
    if llm is not None and llm.status is not ModelStatus.SUCCESS:
        failures.append(f"llm:{llm.error_code}")
    if retrieval and all(result.status is SearchStatus.FAILED for result in retrieval):
        return FailureClassification(DegradationState.TOTAL_UNAVAILABLE, tuple(failures))
    if retrieval and all(result.status is SearchStatus.EMPTY for result in retrieval) and not failures:
        return FailureClassification(DegradationState.ZERO_EVIDENCE)
    if failures:
        return FailureClassification(DegradationState.PARTIAL, tuple(failures))
    return FailureClassification(DegradationState.HEALTHY)
