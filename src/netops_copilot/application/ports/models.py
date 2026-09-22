"""带结构化结果和使用量元数据的模型 provider 端口。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ModelStatus(StrEnum):
    """向降级逻辑暴露的 provider 结果状态。"""

    SUCCESS = "success"
    MALFORMED = "malformed"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


class ModelErrorCode(StrEnum):
    """不包含响应或秘密内容的安全 provider 错误类别。"""

    INVALID_RESPONSE = "invalid_response"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class UsageMetadata:
    """附加到每次成功模型响应的 token/成本信息。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.total_tokens) < 0:
            raise ValueError("usage token counts cannot be negative")
        if self.estimated_cost_usd is not None and (
            self.estimated_cost_usd < 0 or not math.isfinite(self.estimated_cost_usd)
        ):
            raise ValueError("estimated cost must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """有边界的文本生成请求。"""

    prompt: str
    system: str = ""
    max_tokens: int = 512

    def __post_init__(self) -> None:
        if not self.prompt.strip() or self.max_tokens < 1:
            raise ValueError("LLM request requires prompt and positive max_tokens")


@dataclass(frozen=True, slots=True)
class LLMResult:
    """结构化 LLM 响应或安全失败结果。"""

    status: ModelStatus
    text: str = ""
    usage: UsageMetadata | None = None
    error_code: ModelErrorCode | None = None

    def __post_init__(self) -> None:
        if self.status is ModelStatus.SUCCESS and not self.text.strip():
            raise ValueError("successful LLM result requires text")
        if self.status is ModelStatus.MALFORMED and self.error_code is None:
            raise ValueError("malformed LLM result requires an error code")
        if self.status in {ModelStatus.TIMEOUT, ModelStatus.UNAVAILABLE} and self.error_code is None:
            raise ValueError("failed LLM result requires an error code")
        if self.status is ModelStatus.SUCCESS and self.error_code is not None:
            raise ValueError("successful LLM result cannot carry an error")


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    """批量 Embedding 请求。"""

    texts: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.texts or any(not text.strip() for text in self.texts):
            raise ValueError("embedding request requires non-empty texts")


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """结构化 Embedding 向量或安全失败结果。"""

    status: ModelStatus
    vectors: tuple[tuple[float, ...], ...] = ()
    usage: UsageMetadata | None = None
    error_code: ModelErrorCode | None = None

    def __post_init__(self) -> None:
        if self.status is ModelStatus.SUCCESS:
            if not self.vectors or any(not vector for vector in self.vectors):
                raise ValueError("successful embedding result requires vectors")
            dimensions = {len(vector) for vector in self.vectors}
            if len(dimensions) != 1 or any(not math.isfinite(value) for vector in self.vectors for value in vector):
                raise ValueError("embedding vectors must be finite and rectangular")
        elif self.error_code is None:
            raise ValueError("failed embedding result requires an error code")


@dataclass(frozen=True, slots=True)
class RerankRequest:
    """发送给可选 reranker 的查询和候选文本。"""

    query: str
    candidates: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.query.strip() or any(not chunk_id.strip() or not text.strip() for chunk_id, text in self.candidates):
            raise ValueError("rerank request contains blank query or candidate")


@dataclass(frozen=True, slots=True)
class RerankResult:
    """可选 reranker 返回的候选分数。"""

    status: ModelStatus
    scores: tuple[tuple[str, float], ...] = ()
    usage: UsageMetadata | None = None
    error_code: ModelErrorCode | None = None

    def __post_init__(self) -> None:
        if self.status is ModelStatus.SUCCESS:
            if not self.scores or any(not chunk_id.strip() or not math.isfinite(score) for chunk_id, score in self.scores):
                raise ValueError("successful rerank result requires finite scores")
        elif self.error_code is None:
            raise ValueError("failed rerank result requires an error code")


class LLMPort(Protocol):
    def complete(self, request: LLMRequest, timeout_seconds: float = 30.0) -> LLMResult:
        """生成结构化答案或失败结果。"""


class EmbeddingPort(Protocol):
    def embed(self, request: EmbeddingRequest, timeout_seconds: float = 30.0) -> EmbeddingResult:
        """为批次生成 Embedding，并返回使用量元数据或失败结果。"""


class RerankerPort(Protocol):
    def rerank(self, request: RerankRequest, timeout_seconds: float = 10.0) -> RerankResult:
        """为候选项评分，或报告可选 provider 失败。"""


class LocalLLMPort(LLMPort, Protocol):
    """预留的本地 LLM 契约；不会自动选择实现。"""


class LocalEmbeddingPort(EmbeddingPort, Protocol):
    """预留的本地 Embedding 契约；可用性必须显式声明。"""
