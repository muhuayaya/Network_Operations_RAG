"""带显式应用服务注入的版本化 FastAPI 传输层。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from netops_copilot.application.demo_services import ApplicationServiceUnavailable

Handler = Callable[[Mapping[str, Any]], Any]


class ApiServiceError(Exception):
    """映射为 JSON API 响应的稳定应用错误。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class ApiServices:
    """传输层使用的显式处理器；不通过隐藏的全局服务查找。"""

    query: Handler | None = None
    diagnose: Handler | None = None
    diff: Handler | None = None
    device_context: Handler | None = None
    sources: Handler | None = None
    ingestion: Handler | None = None
    evaluation: Handler | None = None
    trace: Handler | None = None
    dependencies: dict[str, bool] = field(default_factory=lambda: {"active-index": False})

    @classmethod
    def from_container(cls, container: Any) -> ApiServices:
        """将显式应用服务容器适配为 REST 处理器。

        此边界有意采用鸭子类型。应用层因此保持独立于 FastAPI，
        运行时只需提供 ``api_handlers()`` 和 ``health_dependencies()``。
        """
        if isinstance(container, cls):
            return container
        handlers = container.api_handlers()
        dependencies = container.health_dependencies()
        return cls(
            query=handlers.get("query"),
            diagnose=handlers.get("diagnose"),
            diff=handlers.get("diff"),
            device_context=handlers.get("device_context"),
            sources=handlers.get("sources"),
            ingestion=handlers.get("ingestion"),
            evaluation=handlers.get("evaluation"),
            trace=handlers.get("trace"),
            dependencies=dict(dependencies),
        )


class QueryRequestDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="要检索的网络运维问题")
    site_id: str | None = Field(default=None, description="按站点 ID 过滤")
    device_id: str | None = Field(default=None, description="按设备 ID 过滤")
    vendor: str | None = Field(default=None, description="按厂商过滤")
    os_version: str | None = Field(default=None, description="按系统版本过滤")
    security_level: str | None = Field(default=None, description="按证据安全级别过滤")
    mode: str | None = Field(default=None, description="检索模式：dense-only、lexical-only、hybrid 或 hybrid-rerank")
    limit: int = Field(default=10, ge=1, le=100, description="返回候选证据数量，范围 1 到 100")


class DiagnosisRequestDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident: dict[str, Any] = Field(description="模拟事故信号")
    candidates: list[dict[str, Any]] = Field(default_factory=list, description="候选证据列表")


class DiffRequestDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor: str = Field(min_length=1, description="配置厂商")
    baseline: str = Field(min_length=1, description="基线配置快照")
    current: str = Field(min_length=1, description="当前配置快照")


class IngestionRequestDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, description="知识来源 ID")


def create_app(services: ApiServices | None = None) -> FastAPI:
    """创建 REST 应用，但不构造 provider 或访问设备。"""
    configured = services or ApiServices()
    app = FastAPI(title="面向企业IT与网络运维的RAG系统", version="0.1.0", docs_url=None)
    app.state.services = configured

    @app.get("/docs", include_in_schema=False)
    async def swagger_docs(request: Request) -> HTMLResponse:
        root_path = request.scope.get("root_path", "").rstrip("/")
        page = get_swagger_ui_html(
            openapi_url=f"{root_path}{app.openapi_url}",
            title="面向企业IT与网络运维的RAG系统 - 接口文档",
        )
        html = bytes(page.body).decode("utf-8").replace("<html>", '<html lang="zh-CN">', 1)
        html = html.replace(
            "</body>",
            f'<script src="{root_path}/docs/i18n.js"></script>\n</body>',
            1,
        )
        return HTMLResponse(html)

    @app.get("/docs/i18n.js", include_in_schema=False)
    async def swagger_translation() -> Response:
        script = Path(__file__).with_name("swagger_zh.js").read_text(encoding="utf-8")
        return Response(script, media_type="application/javascript")

    @app.exception_handler(ApiServiceError)
    async def handle_service_error(request: Request, error: ApiServiceError) -> JSONResponse:
        return _error_response(request, error.code, error.message, error.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return _error_response(request, "invalid_request", _validation_message(error), 422)

    @app.exception_handler(ValueError)
    async def handle_value_error(request: Request, error: ValueError) -> JSONResponse:
        return _error_response(request, "invalid_request", str(error), 400)

    @app.get("/health/live", summary="存活检查", description="确认 API 进程正在运行。")
    async def liveness() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready", summary="就绪检查", description="查看活动索引等依赖是否可用。")
    async def readiness() -> dict[str, Any]:
        dependencies = configured.dependencies
        unavailable = sorted(name for name, available in dependencies.items() if not available)
        return {
            "status": "ready" if not unavailable else "not_ready",
            "dependencies": {name: dependencies[name] for name in sorted(dependencies)},
            "unavailable": unavailable,
        }

    @app.post("/api/v1/query", summary="知识检索", description="检索网络运维知识并返回候选证据。")
    async def query(payload: QueryRequestDto) -> Any:
        return await _dispatch(configured.query, payload.model_dump())

    @app.post("/api/v1/incidents/diagnose", summary="事故研判", description="分析模拟事故的证据。")
    async def diagnose(payload: DiagnosisRequestDto) -> Any:
        return await _dispatch(configured.diagnose, payload.model_dump())

    @app.post("/api/v1/configs/diff", summary="配置差异比较", description="确定性比较两份配置快照。")
    async def config_diff(payload: DiffRequestDto) -> Any:
        return await _dispatch(configured.diff, payload.model_dump())

    @app.get("/api/v1/devices/{device_id}/context", summary="设备上下文", description="读取设备上下文。")
    async def device_context(device_id: str) -> Any:
        return await _dispatch(configured.device_context, {"device_id": device_id})

    @app.get("/api/v1/sources", summary="知识来源", description="列出可用的知识来源。")
    async def sources() -> Any:
        return await _dispatch(configured.sources, {})

    @app.post("/api/v1/ingestion", summary="数据摄取", description="提交数据摄取请求。")
    async def ingestion(payload: IngestionRequestDto) -> Any:
        return await _dispatch(configured.ingestion, payload.model_dump())

    @app.get("/api/v1/evaluation", summary="评测结果", description="查看检索与问答评测结果。")
    async def evaluation() -> Any:
        return await _dispatch(configured.evaluation, {})

    @app.get("/api/v1/traces/{trace_id}", summary="调用追踪", description="读取指定调用的追踪记录。")
    async def trace(trace_id: str) -> Any:
        return await _dispatch(configured.trace, {"trace_id": trace_id})

    return app


def create_app_from_services(container: Any) -> FastAPI:
    """根据应用层拥有的只读服务容器创建 REST 应用。"""
    return create_app(ApiServices.from_container(container))


async def _dispatch(handler: Handler | None, payload: Mapping[str, Any]) -> Any:
    if handler is None:
        raise ApiServiceError("service_unavailable", "应用服务未配置", 503)
    try:
        result = handler(payload)
        if hasattr(result, "__await__"):
            result = await result
    except ApplicationServiceUnavailable as error:
        raise ApiServiceError("service_unavailable", str(error), 503) from error
    except (TypeError, ValueError) as error:
        raise ApiServiceError("invalid_request", str(error), 400) from error
    return jsonable_encoder(result)


def _error_response(request: Request, code: str, message: str, status_code: int) -> JSONResponse:
    trace_id = request.headers.get("x-trace-id", f"trace-{uuid4().hex}")
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}, "trace_id": trace_id},
        headers={"X-Trace-Id": trace_id},
    )


def _validation_message(error: RequestValidationError) -> str:
    """将 Pydantic 校验失败转换为简洁的中文用户消息。"""

    messages: list[str] = []
    field_labels = {
        "query": "查询问题",
        "limit": "返回数量",
        "incident": "事故信号",
        "candidates": "候选证据",
        "vendor": "厂商",
        "baseline": "基线配置",
        "current": "当前配置",
        "source_id": "来源 ID",
    }
    for item in error.errors():
        location = item.get("loc", ())
        field = next((str(part) for part in reversed(location) if part != "body"), "请求体")
        label = field_labels.get(field, field)
        error_type = str(item.get("type", ""))
        context = item.get("ctx") or {}
        if error_type == "string_too_short":
            message = f"{label}至少需要 {context.get('min_length', 1)} 个字符"
        elif error_type == "less_than_equal":
            message = f"{label}不能大于 {context.get('le', '')}"
        elif error_type == "greater_than_equal":
            message = f"{label}不能小于 {context.get('ge', '')}"
        elif error_type == "missing":
            message = f"缺少必填字段：{label}"
        elif error_type == "extra_forbidden":
            message = f"不允许使用字段：{label}"
        elif error_type == "json_invalid":
            message = "请求体不是有效的 JSON"
        else:
            message = f"{label}参数格式不正确"
        messages.append(message)
    return "；".join(messages) or "请求参数校验失败"


app = create_app()

__all__ = [
    "ApiServiceError",
    "ApiServices",
    "DiagnosisRequestDto",
    "DiffRequestDto",
    "IngestionRequestDto",
    "QueryRequestDto",
    "app",
    "create_app",
    "create_app_from_services",
]
