"""REST 契约和通用错误映射测试。"""

from __future__ import annotations

import asyncio
import unittest

from starlette.requests import Request

from netops_copilot.interfaces.api import ApiServiceError, ApiServices, QueryRequestDto, create_app


class ApiAppTests(unittest.TestCase):
    def test_liveness_readiness_and_versioned_routes(self) -> None:
        app = create_app(ApiServices(dependencies={"milvus": False, "postgres": True}))
        route_by_path = {route.path: route for route in app.routes}
        self.assertEqual(asyncio.run(route_by_path["/health/live"].endpoint()), {"status": "live"})
        readiness = asyncio.run(route_by_path["/health/ready"].endpoint())
        self.assertEqual(readiness["status"], "not_ready")
        self.assertEqual(readiness["unavailable"], ["milvus"])
        paths = {route.path for route in app.routes}
        self.assertTrue({
            "/api/v1/query",
            "/api/v1/incidents/diagnose",
            "/api/v1/configs/diff",
            "/api/v1/devices/{device_id}/context",
            "/api/v1/sources",
            "/api/v1/ingestion",
            "/api/v1/evaluation",
            "/api/v1/traces/{trace_id}",
        }.issubset(paths))
        self.assertIn("/api/v1/configs/diff", app.openapi()["paths"])

    def test_handlers_and_common_errors_are_consistent(self) -> None:
        app = create_app(ApiServices(query=lambda payload: {"echo": payload["query"]}))
        route_by_path = {route.path: route for route in app.routes}
        response = asyncio.run(route_by_path["/api/v1/query"].endpoint(QueryRequestDto(query="OSPF")))
        self.assertEqual(response, {"echo": "OSPF"})
        with self.assertRaises(ApiServiceError) as missing:
            asyncio.run(route_by_path["/api/v1/sources"].endpoint())
        self.assertEqual(missing.exception.status_code, 503)
        with self.assertRaises(ValueError):
            QueryRequestDto(query="")

    def test_swagger_ui_uses_chinese_labels_without_changing_api_contract(self) -> None:
        app = create_app()
        route_by_path = {route.path: route for route in app.routes}
        page = asyncio.run(route_by_path["/docs"].endpoint(Request({"type": "http", "root_path": ""})))
        html = page.body.decode("utf-8")
        self.assertIn('<html lang="zh-CN">', html)
        self.assertIn('/docs/i18n.js', html)

        script = asyncio.run(route_by_path["/docs/i18n.js"].endpoint())
        javascript = script.body.decode("utf-8")
        self.assertIn('"Cancel": "取消"', javascript)
        self.assertIn('"Reset": "重置"', javascript)
        self.assertIn('content: "必填"', javascript)
        self.assertIn("MutationObserver", javascript)

        openapi = app.openapi()
        self.assertEqual(openapi["paths"]["/api/v1/query"]["post"]["summary"], "知识检索")
        self.assertIn("/api/v1/query", openapi["paths"])


if __name__ == "__main__":
    unittest.main()
