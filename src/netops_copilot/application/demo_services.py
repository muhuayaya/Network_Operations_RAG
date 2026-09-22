"""本地演示使用的小型只读应用服务组合。

传输层只处理字典和可调用对象。本模块把用例连线保留在应用层，
避免 FastAPI 和 Streamlit 各自维护一套业务实现。所有依赖都显式注入：
未配置的检索服务会明确报告不可用，不会伪装成存在活动索引。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from netops_copilot.application.config_diff import ConfigurationDiffer
from netops_copilot.application.grounded_answers import GroundedAnswerService, ModelSource
from netops_copilot.application.ports.search import SearchFilters
from netops_copilot.application.query import QueryMode, QueryResult, QueryService

Handler = Callable[[Mapping[str, Any]], Any]


class ApplicationServiceUnavailable(RuntimeError):
    """必需的只读依赖尚未配置时抛出的异常。"""


class QueryVectorizer(Protocol):
    """演示检索适配器使用的最小查询向量契约。"""

    def __call__(self, query: str) -> Sequence[float]:
        """为规范化查询返回一个向量。"""


@dataclass(slots=True)
class DemoApplicationServices:
    """由 REST 和 Streamlit 共享的显式只读服务。

    ``query_handler`` 适用于运行时索引构建器提供自定义检索管线的场景。
    ``query_service`` + ``vectorizer`` 覆盖默认的进程内 QueryService 路径。
    两者被设计为互斥替代方案，缺少活动索引时不能静默绕过检查。
    """

    query_handler: Handler | None = None
    query_service: QueryService | None = None
    vectorizer: QueryVectorizer | None = None
    diff_handler: Handler | None = None
    diagnose_handler: Handler | None = None
    device_context_handler: Handler | None = None
    dependencies: dict[str, bool] | None = None
    differ: ConfigurationDiffer | None = None
    trace_handler: Handler | None = None
    sources_handler: Handler | None = None
    ingestion_handler: Handler | None = None
    evaluation_handler: Handler | None = None
    answer_service: GroundedAnswerService | None = None

    def api_handlers(self) -> Mapping[str, Handler]:
        """只返回 REST 适配器支持的处理器。"""
        handlers: dict[str, Handler] = {"diff": self.diff}
        if self.query_handler is not None or (self.query_service is not None and self.vectorizer is not None):
            handlers["query"] = self.query
        if self.diagnose_handler is not None:
            handlers["diagnose"] = self.diagnose
        if self.device_context_handler is not None:
            handlers["device_context"] = self.device_context
        if self.trace_handler is not None:
            handlers["trace"] = self.trace
        if self.sources_handler is not None:
            handlers["sources"] = self.sources
        if self.ingestion_handler is not None:
            handlers["ingestion"] = self.ingestion
        if self.evaluation_handler is not None:
            handlers["evaluation"] = self.evaluation
        return handlers

    def ui_handlers(self) -> Mapping[str, Callable[..., Any]]:
        """返回符合 Streamlit 调用方式的页面回调。"""
        handlers: dict[str, Callable[..., Any]] = {
            "configuration_diff": lambda vendor, baseline, current: self.diff(
                {"vendor": vendor, "baseline": baseline, "current": current}
            )
        }
        if self.answer_service is not None:
            handlers["knowledge_query"] = self.answer
        elif self.query_handler is not None or (self.query_service is not None and self.vectorizer is not None):
            handlers["knowledge_query"] = lambda value: self.query(
                value if isinstance(value, Mapping) else {"query": value}
            )
        if self.trace_handler is not None:
            handlers["trace_evaluation"] = lambda: self.trace({})
        return handlers

    def health_dependencies(self) -> Mapping[str, bool]:
        """暴露依赖状态，但不暴露客户端对象或凭据。"""
        return dict(self.dependencies or {"active-index": False})

    def query(self, payload: Mapping[str, Any]) -> Any:
        """执行注入的检索服务；未配置时返回安全的不可用错误。"""
        if self.query_handler is not None:
            return self.query_handler(payload)
        if self.query_service is None or self.vectorizer is None:
            raise ApplicationServiceUnavailable("知识检索服务未配置")
        query = str(payload.get("query", ""))
        filters = SearchFilters(
            site_id=_optional_text(payload.get("site_id")),
            device_id=_optional_text(payload.get("device_id")),
            vendor=_optional_text(payload.get("vendor")),
            os_version=_optional_text(payload.get("os_version")),
            security_level=_optional_text(payload.get("security_level")),
        )
        mode_value = _optional_text(payload.get("mode")) or QueryMode.HYBRID.value
        try:
            mode = QueryMode(mode_value)
        except ValueError as error:
            raise ValueError(f"不支持的检索模式：{mode_value}") from error
        result = self.query_service.search(
            query=query,
            query_vector=self.vectorizer(query),
            filters=filters,
            mode=mode,
            limit=_positive_int(payload.get("limit", 10), "limit"),
        )
        return _query_result_payload(result)

    def answer(self, payload: Mapping[str, Any] | str) -> Any:
        """执行带 Milvus 证据和引用的自然语言回答。"""
        if self.answer_service is None:
            return self.query({"query": payload} if isinstance(payload, str) else payload)
        values = {"query": payload} if isinstance(payload, str) else dict(payload)
        query = _required_text(values.get("query"), "query")
        mode_value = _optional_text(values.get("mode")) or QueryMode.HYBRID.value
        try:
            mode = QueryMode(mode_value)
        except ValueError as error:
            raise ValueError(f"不支持的检索模式：{mode_value}") from error
        return self.answer_service.answer(
            question=query,
            filters=SearchFilters(
                site_id=_optional_text(values.get("site_id")),
                device_id=_optional_text(values.get("device_id")),
                vendor=_optional_text(values.get("vendor")),
                os_version=_optional_text(values.get("os_version")),
                security_level=_optional_text(values.get("security_level")),
            ),
            mode=mode,
            rerank=bool(values.get("rerank", False)),
            limit=_positive_int(values.get("limit", 5), "limit"),
            model_source=_optional_text(values.get("model_source")) or ModelSource.DASHSCOPE.value,
        )

    def diff(self, payload: Mapping[str, Any]) -> Any:
        """无副作用地计算确定性配置差异。"""
        if self.diff_handler is not None:
            return self.diff_handler(payload)
        vendor = _required_text(payload.get("vendor"), "vendor")
        baseline = _required_text(payload.get("baseline"), "baseline")
        current = _required_text(payload.get("current"), "current")
        differ = self.differ or ConfigurationDiffer()
        result = differ.diff(baseline, current, vendor=vendor)
        return {
            "vendor": result.vendor.value,
            "changed": result.changed,
            "risk_level": result.risk_level.value,
            "changes": [_change_payload(change) for change in result.changes],
        }

    def diagnose(self, payload: Mapping[str, Any]) -> Any:
        """执行注入的确定性事故研判处理器。"""
        if self.diagnose_handler is None:
            raise ApplicationServiceUnavailable("事故研判服务未配置")
        return self.diagnose_handler(payload)

    def device_context(self, payload: Mapping[str, Any]) -> Any:
        """读取由固定演示数据提供的设备上下文。"""
        if self.device_context_handler is None:
            raise ApplicationServiceUnavailable("设备上下文服务未配置")
        return self.device_context_handler(payload)

    def trace(self, payload: Mapping[str, Any]) -> Any:
        """通过注入的、由仓储支持的回调读取 Trace。"""
        if self.trace_handler is None:
            raise ApplicationServiceUnavailable("Trace 服务未配置")
        return self.trace_handler(payload)

    def sources(self, payload: Mapping[str, Any]) -> Any:
        """通过注入的只读回调列出来源元数据。"""
        if self.sources_handler is None:
            raise ApplicationServiceUnavailable("知识来源服务未配置")
        return self.sources_handler(payload)

    def ingestion(self, payload: Mapping[str, Any]) -> Any:
        """确认演示来源已经存在，但不修改活动索引。"""
        if self.ingestion_handler is None:
            raise ApplicationServiceUnavailable("数据摄取服务未配置")
        return self.ingestion_handler(payload)

    def evaluation(self, payload: Mapping[str, Any]) -> Any:
        """读取已配置的评测摘要，不执行新的评测。"""
        if self.evaluation_handler is None:
            raise ApplicationServiceUnavailable("评测服务未配置")
        return self.evaluation_handler(payload)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        labels = {"vendor": "厂商", "baseline": "基线配置", "current": "当前配置"}
        raise ValueError(f"{labels.get(field, field)}不能为空")
    return text


def _positive_int(value: Any, field: str) -> int:
    try:
        converted = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be a positive integer") from error
    if converted < 1:
        raise ValueError(f"{field} must be a positive integer")
    return converted


def _query_result_payload(result: QueryResult) -> dict[str, Any]:
    return {
        "mode": result.mode.value,
        "state": result.state.value,
        "degradation": list(result.degradation),
        "candidates": [_candidate_payload(candidate) for candidate in result.candidates],
    }


def _candidate_payload(candidate: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chunk_id": candidate.chunk_id,
        "text": getattr(candidate, "text", ""),
        "metadata": dict(candidate.metadata),
    }
    if hasattr(candidate, "fused_score"):
        payload["score"] = candidate.fused_score
        payload["channel_ranks"] = [
            {"channel": channel.value, "rank": rank}
            for channel, rank in candidate.channel_ranks
        ]
    else:
        payload["score"] = candidate.raw_score
        payload["channel"] = candidate.channel.value
        payload["rank"] = candidate.rank
    return payload


def _change_payload(change: Any) -> dict[str, Any]:
    return {
        "section": change.section,
        "path": change.path,
        "operation": change.operation.value,
        "before": change.before,
        "after": change.after,
        "line_refs": list(change.line_refs),
        "risk_tags": list(change.risk_tags),
        "risk_level": change.risk_level.value,
    }


__all__ = ["ApplicationServiceUnavailable", "DemoApplicationServices", "QueryVectorizer"]
