"""查询规范化和检索前主体授权。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from netops_copilot.application.ports.search import (
    SearchCandidate,
    SearchFilters,
    SearchResult,
    SearchStatus,
)
from netops_copilot.domain.inventory import DataSecurityLevel
from netops_copilot.domain.knowledge import KnowledgeChunk
from netops_copilot.domain.shared.identity import Principal, SecurityLevel


class QueryAuthorizationError(PermissionError):
    """范围缺失或被禁止时，在后端检索前抛出的异常。"""


@dataclass(frozen=True, slots=True)
class AuthorizedQuery:
    """可安全发送给检索后端的规范化查询和过滤条件。"""

    query: str
    filters: SearchFilters


def normalize_query(query: str, *, max_chars: int = 2_000) -> str:
    """压缩不可信空白字符，并限制查询长度。"""
    normalized = re.sub(r"\s+", " ", query).strip()
    if not normalized:
        raise QueryAuthorizationError("query cannot be blank")
    if len(normalized) > max_chars:
        raise QueryAuthorizationError("query exceeds maximum length")
    return normalized


def authorize_query(principal: Principal, query: str, filters: SearchFilters) -> AuthorizedQuery:
    """在执行候选检索前要求调用方明确指定已授权站点。"""
    normalized_query = normalize_query(query)
    if filters.site_id is None:
        raise QueryAuthorizationError("site filter is required for authorized retrieval")
    evidence_level = (
        SecurityLevel.RESTRICTED if filters.security_level == SecurityLevel.RESTRICTED.value else SecurityLevel.BASIC
    )
    if filters.security_level not in {None, "public", "internal", "restricted", "basic"}:
        raise QueryAuthorizationError("unsupported security filter")
    if not principal.can_access(filters.site_id, evidence_level):
        raise QueryAuthorizationError("principal is not authorized for the requested site or security level")
    if principal.security_level is SecurityLevel.BASIC and filters.security_level is None:
        # 当前检索后端只暴露一个精确的安全级别过滤条件。
        # 调用方未明确指定级别时，基础检索默认限制为 internal，
        # 防止受限记录进入后端查询。
        filters = replace(filters, security_level=DataSecurityScope.BASIC_MAX.value)
    return AuthorizedQuery(normalized_query, filters)


class DataSecurityScope:
    """普通主体可读取的最高级别对应的后端过滤值。"""

    BASIC_MAX = DataSecurityLevel.INTERNAL


def filter_search_result(principal: Principal, result: SearchResult) -> SearchResult:
    """在记录证据或 Trace 前执行纵深防御式候选过滤。"""
    if result.status is not SearchStatus.MATCHES:
        return result
    allowed = tuple(candidate for candidate in result.candidates if _candidate_allowed(principal, candidate))
    return SearchResult.matches(allowed) if allowed else SearchResult.empty()


def filter_knowledge_chunks(principal: Principal, chunks: Iterable[KnowledgeChunk]) -> tuple[KnowledgeChunk, ...]:
    """在组装证据前按站点和权限级别过滤检索结果。"""
    return tuple(chunk for chunk in chunks if _chunk_allowed(principal, chunk))


def _candidate_allowed(principal: Principal, candidate: SearchCandidate) -> bool:
    site_id = candidate.metadata.get("site_id")
    if site_id is not None and site_id not in principal.allowed_site_ids:
        return False
    security_level = candidate.metadata.get("security_level", "internal")
    return not (security_level == "restricted" and principal.security_level is SecurityLevel.BASIC)


def _chunk_allowed(principal: Principal, chunk: KnowledgeChunk) -> bool:
    site_id = chunk.metadata.get("site_id")
    if site_id is not None and site_id not in principal.allowed_site_ids:
        return False
    return not (
        chunk.security_level.value == "restricted" and principal.security_level is SecurityLevel.BASIC
    )
