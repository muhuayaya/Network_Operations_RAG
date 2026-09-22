"""REST/MCP 语义一致性测试。"""

from __future__ import annotations

import asyncio
import unittest

from netops_copilot.interfaces import SemanticResponse, semantic_projection
from netops_copilot.interfaces.api import ApiServices, QueryRequestDto, create_app
from netops_copilot.interfaces.mcp import create_mcp_server


class InterfaceParityTests(unittest.TestCase):
    def test_identical_application_response_projects_identically(self) -> None:
        response = SemanticResponse(
            data={"answer": "check MTU"},
            evidence_ids=("chunk-1", "chunk-2"),
            degradation=("reranker:unavailable",),
            trace_id="trace-1",
        )
        rest_app = create_app(ApiServices(query=lambda payload: response))
        rest_route = next(route for route in rest_app.routes if route.path == "/api/v1/query")
        rest_result = asyncio.run(rest_route.endpoint(QueryRequestDto(query="OSPF")))
        mcp = create_mcp_server({"query_operations_knowledge": lambda payload: response})
        mcp_result = mcp.call("query_operations_knowledge", {"query": "OSPF"})

        self.assertEqual(semantic_projection(rest_result), semantic_projection(mcp_result))
        self.assertEqual(semantic_projection(rest_result).evidence_ids, ("chunk-1", "chunk-2"))
        self.assertEqual(semantic_projection(rest_result).trace_id, "trace-1")


if __name__ == "__main__":
    unittest.main()
