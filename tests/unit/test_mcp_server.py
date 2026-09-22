"""MCP 允许列表和 stdio 隔离测试。"""

from __future__ import annotations

import io
import json
import unittest

from netops_copilot.interfaces.mcp import create_mcp_server


class McpServerTests(unittest.TestCase):
    def test_discovery_contains_only_safe_named_tools(self) -> None:
        server = create_mcp_server({"get_trace": lambda arguments: {"trace_id": arguments["trace_id"]}})
        names = {tool["name"] for tool in server.list_tools()}
        self.assertEqual(
            names,
            {
                "query_operations_knowledge",
                "diagnose_simulated_incident",
                "explain_configuration_diff",
                "get_device_context",
                "list_knowledge_sources",
                "get_trace",
            },
        )
        self.assertNotIn("execute_command", names)
        self.assertEqual(server.call("get_trace", {"trace_id": "t-1"}), {"trace_id": "t-1"})

    def test_stdio_emits_json_only_and_rejects_mutation_tool(self) -> None:
        server = create_mcp_server()
        input_stream = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
            + json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "configure_device", "arguments": {}},
                }
            )
            + "\n"
        )
        output_stream = io.StringIO()
        server.run_stdio(input_stream, output_stream)
        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertIn("tools", responses[0]["result"])
        self.assertEqual(responses[1]["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
