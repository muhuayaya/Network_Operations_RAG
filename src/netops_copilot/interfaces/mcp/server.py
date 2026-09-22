"""安全的 MCP 形状工具注册表和 stdio 传输层。

适配器有意只暴露命名的应用操作，不提供 shell、原始 SSH、设备写入
或任意方法分派能力。
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TextIO

Handler = Callable[[Mapping[str, Any]], Any]
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class McpTool:
    """一个命名的只读应用工具。"""

    name: str
    description: str
    handler: Handler


class SafeMcpServer:
    """发现并调用允许列表中的只读工具。"""

    def __init__(self, handlers: Mapping[str, Handler] | None = None) -> None:
        supplied = dict(handlers or {})
        unknown = set(supplied) - set(_TOOL_DESCRIPTIONS)
        if unknown:
            raise ValueError(f"不支持的 MCP 工具：{', '.join(sorted(unknown))}")
        self._tools = {
            name: McpTool(name, description, supplied.get(name, _unconfigured))
            for name, description in _TOOL_DESCRIPTIONS.items()
        }

    def list_tools(self) -> tuple[dict[str, str], ...]:
        """返回稳定的发现元数据，不暴露 Python 可调用对象。"""
        return tuple(
            {"name": tool.name, "description": tool.description}
            for tool in self._tools.values()
        )

    def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> Any:
        try:
            tool = self._tools[name]
        except KeyError as error:
            raise ValueError(f"MCP 工具不在许可列表中：{name}") from error
        return tool.handler(arguments or {})

    def handle_message(self, message: Mapping[str, Any]) -> dict[str, Any]:
        """处理一个类似 JSON-RPC 的请求，并保持协议输出确定。"""
        request_id = message.get("id")
        method = message.get("method")
        try:
            if method == "tools/list":
                result: Any = {"tools": self.list_tools()}
            elif method == "tools/call":
                params = message.get("params", {})
                if not isinstance(params, Mapping) or not isinstance(params.get("name"), str):
                    raise ValueError("tools/call 必须提供工具名称")
                result = self.call(params["name"], params.get("arguments", {}))
            else:
                raise ValueError(f"不支持的 MCP 方法：{method}")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except ValueError as error:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": str(error)},
            }

    def run_stdio(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        """处理按换行分隔的协议消息；诊断信息写入 stderr。"""
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
                if not isinstance(message, Mapping):
                    raise TypeError("MCP 消息必须是对象")
                response = self.handle_message(message)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                LOGGER.warning("MCP 输入无效：%s", error)
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "请求无效"},
                }
            stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            stdout.flush()


_TOOL_DESCRIPTIONS = {
    "query_operations_knowledge": "检索经过授权的网络运维知识。",
    "diagnose_simulated_incident": "根据确定性证据研判模拟事故。",
    "explain_configuration_diff": "解释确定性的配置差异。",
    "get_device_context": "读取设备上下文快照。",
    "list_knowledge_sources": "列出经过授权的知识来源。",
    "get_trace": "读取查询或摄取 Trace。",
}


def _unconfigured(arguments: Mapping[str, Any]) -> Any:
    del arguments
    raise ValueError("MCP 应用服务未配置")


def create_mcp_server(handlers: Mapping[str, Handler] | None = None) -> SafeMcpServer:
    """根据显式应用处理器构建安全 MCP 服务。"""
    return SafeMcpServer(handlers)


__all__ = ["McpTool", "SafeMcpServer", "create_mcp_server"]
