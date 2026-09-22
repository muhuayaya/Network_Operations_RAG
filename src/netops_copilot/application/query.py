"""带可选重排的 Dense/Lexical/Hybrid 基线查询编排。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from netops_copilot.application.authorization import (
    authorize_query,
    filter_search_result,
    normalize_query,
)
from netops_copilot.application.degradation import DegradationState, classify_query
from netops_copilot.application.fusion import FusedCandidate, rrf_fuse
from netops_copilot.application.ports.models import (
    ModelStatus,
    RerankerPort,
    RerankRequest,
)
from netops_copilot.application.ports.search import (
    DenseSearchPort,
    LexicalSearchPort,
    SearchCandidate,
    SearchFilters,
    SearchResult,
    SearchStatus,
)
from netops_copilot.domain.shared.identity import Principal


class QueryMode(StrEnum):
    """首个查询基线对外提供的检索模式。"""

    DENSE_ONLY = "dense-only"
    LEXICAL_ONLY = "lexical-only"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid-rerank"


@dataclass(frozen=True, slots=True)
class QueryResult:
    """候选结果及明确的降级标记。"""

    mode: QueryMode
    candidates: tuple[SearchCandidate | FusedCandidate, ...]
    degradation: tuple[str, ...] = ()
    state: DegradationState = DegradationState.HEALTHY


class QueryService:
    """组合检索通道，但不泄露后端特有行为。"""

    def __init__(
        self,
        dense: DenseSearchPort,
        lexical: LexicalSearchPort,
        reranker: RerankerPort | None = None,
        *,
        minimum_dense_score: float | None = None,
    ) -> None:
        self._dense = dense
        self._lexical = lexical
        self._reranker = reranker
        if minimum_dense_score is not None and not math.isfinite(minimum_dense_score):
            raise ValueError("minimum_dense_score must be finite")
        self._minimum_dense_score = minimum_dense_score

    def search(
        self,
        *,
        query: str,
        query_vector: Sequence[float],
        filters: SearchFilters,
        mode: QueryMode = QueryMode.HYBRID,
        limit: int = 10,
        candidate_texts: Mapping[str, str] | None = None,
        principal: Principal | None = None,
    ) -> QueryResult:
        if principal is not None:
            authorized = authorize_query(principal, query, filters)
            query, filters = authorized.query, authorized.filters
        else:
            query = normalize_query(query)
        dense_result = self._dense.search(query_vector, filters, limit) if mode is not QueryMode.LEXICAL_ONLY else None
        lexical_result = self._lexical.search(query, filters, limit) if mode is not QueryMode.DENSE_ONLY else None
        if principal is not None:
            if dense_result is not None:
                dense_result = filter_search_result(principal, dense_result)
            if lexical_result is not None:
                lexical_result = filter_search_result(principal, lexical_result)
        dense_result, lexical_result = self._apply_evidence_gate(
            dense_result,
            lexical_result,
            mode,
        )
        degradation: list[str] = []
        for channel, result in (("dense", dense_result), ("lexical", lexical_result)):
            if result is not None and result.status is SearchStatus.FAILED:
                degradation.append(f"{channel}:{result.error_code}")
        if mode is QueryMode.DENSE_ONLY:
            candidates = dense_result.candidates if dense_result and dense_result.status is SearchStatus.MATCHES else ()
            classification = classify_query(dense_result, None)
            return QueryResult(mode, tuple(candidates), tuple(degradation), classification.state)
        if mode is QueryMode.LEXICAL_ONLY:
            candidates = lexical_result.candidates if lexical_result and lexical_result.status is SearchStatus.MATCHES else ()
            classification = classify_query(None, lexical_result)
            return QueryResult(mode, tuple(candidates), tuple(degradation), classification.state)
        valid_results = [result for result in (dense_result, lexical_result) if result is not None and result.status is not SearchStatus.FAILED]
        fused = list(rrf_fuse(valid_results, limit=limit))
        if mode is QueryMode.HYBRID_RERANK:
            supplied_texts = candidate_texts or {
                candidate.chunk_id: candidate.text for candidate in fused if candidate.text
            }
            fused = self._rerank(query, fused, supplied_texts, degradation, limit)
        classification = classify_query(dense_result, lexical_result)
        if any(item.startswith("reranker:") for item in degradation) and classification.state is DegradationState.HEALTHY:
            classification = type(classification)(DegradationState.PARTIAL, tuple(degradation))
        return QueryResult(mode, tuple(fused), tuple(degradation), classification.state)

    def _apply_evidence_gate(
        self,
        dense: SearchResult | None,
        lexical: SearchResult | None,
        mode: QueryMode,
    ) -> tuple[SearchResult | None, SearchResult | None]:
        """将单路低置信 Dense 候选转换为明确的无证据结果。"""
        threshold = self._minimum_dense_score
        if threshold is None or dense is None or dense.status is not SearchStatus.MATCHES:
            return dense, lexical
        if mode not in {QueryMode.DENSE_ONLY, QueryMode.HYBRID, QueryMode.HYBRID_RERANK}:
            return dense, lexical
        if lexical is not None and lexical.status is not SearchStatus.EMPTY:
            return dense, lexical
        if dense.candidates and dense.candidates[0].raw_score < threshold:
            return SearchResult.empty(), lexical
        return dense, lexical

    def _rerank(
        self,
        query: str,
        candidates: list[FusedCandidate],
        candidate_texts: Mapping[str, str],
        degradation: list[str],
        limit: int,
    ) -> list[FusedCandidate]:
        if self._reranker is None:
            degradation.append("reranker:unavailable")
            return candidates
        request = RerankRequest(query, tuple((candidate.chunk_id, candidate_texts[candidate.chunk_id]) for candidate in candidates if candidate.chunk_id in candidate_texts))
        if not request.candidates:
            degradation.append("reranker:no-candidate-text")
            return candidates
        result = self._reranker.rerank(request)
        if result.status is not ModelStatus.SUCCESS:
            degradation.append(f"reranker:{result.error_code}")
            return candidates
        scores = dict(result.scores)
        return sorted(candidates, key=lambda candidate: (-scores.get(candidate.chunk_id, float("-inf")), candidate.chunk_id))[:limit]
