"""REST 和 Streamlit 适配器的显式应用服务连线测试。"""

from __future__ import annotations

import asyncio
import unittest

from netops_copilot.application.demo_services import (
    ApplicationServiceUnavailable,
    DemoApplicationServices,
)
from netops_copilot.interfaces.api import (
    DiagnosisRequestDto,
    IngestionRequestDto,
    QueryRequestDto,
    create_app_from_services,
)
from netops_copilot.interfaces.ui import PageServices


class DemoApplicationServicesTests(unittest.TestCase):
    def test_configuration_diff_is_read_only_and_structured(self) -> None:
        services = DemoApplicationServices()
        result = services.diff(
            {
                "vendor": "Huawei",
                "baseline": "interface Eth1\n ip address 10.0.0.1 255.255.255.0",
                "current": "interface Eth1\n shutdown",
            }
        )
        self.assertTrue(result["changed"])
        self.assertEqual(result["risk_level"], "high")
        self.assertGreaterEqual(len(result["changes"]), 1)

    def test_missing_query_dependency_is_explicitly_unavailable(self) -> None:
        with self.assertRaises(ApplicationServiceUnavailable):
            DemoApplicationServices().query({"query": "OSPF"})

    def test_default_container_does_not_claim_an_active_index(self) -> None:
        services = DemoApplicationServices()
        app = create_app_from_services(services)
        ready = next(route for route in app.routes if route.path == "/health/ready")
        result = asyncio.run(ready.endpoint())
        self.assertEqual(result["status"], "not_ready")
        self.assertEqual(result["unavailable"], ["active-index"])

    def test_container_adapts_to_rest_and_streamlit(self) -> None:
        services = DemoApplicationServices(
            query_handler=lambda payload: {"query": payload["query"], "state": "healthy"},
            dependencies={"active-index": True},
        )
        app = create_app_from_services(services)
        route = next(route for route in app.routes if route.path == "/api/v1/query")
        result = asyncio.run(route.endpoint(QueryRequestDto(query="OSPF")))
        self.assertEqual(result["query"], "OSPF")
        ready = next(route for route in app.routes if route.path == "/health/ready")
        self.assertEqual(asyncio.run(ready.endpoint())["status"], "ready")
        pages = PageServices.from_container(services)
        self.assertEqual(pages.knowledge_query("OSPF")["query"], "OSPF")

    def test_container_injects_source_and_evaluation_handlers_for_rest(self) -> None:
        services = DemoApplicationServices(
            diagnose_handler=lambda payload: {
                "status": "analyzed",
                "scenario_id": payload["incident"]["scenario_id"],
            },
            device_context_handler=lambda payload: {
                "read_only": True,
                "device_id": payload["device_id"],
            },
            sources_handler=lambda _: {"summary": {"source_count": 35}, "sources": []},
            ingestion_handler=lambda payload: {
                "status": "already_indexed",
                "source_id": payload["source_id"],
            },
            evaluation_handler=lambda _: {"status": "not_run", "golden_set": {"case_count": 50}},
            trace_handler=lambda payload: {"trace_id": payload.get("trace_id", "demo-index-active")},
        )
        app = create_app_from_services(services)
        routes = {route.path: route for route in app.routes}

        sources = asyncio.run(routes["/api/v1/sources"].endpoint())
        diagnosis = asyncio.run(
            routes["/api/v1/incidents/diagnose"].endpoint(
                DiagnosisRequestDto(incident={"scenario_id": "inc-ospf-exstart"})
            )
        )
        device_context = asyncio.run(
            routes["/api/v1/devices/{device_id}/context"].endpoint("hw-sz-core-01")
        )
        ingestion = asyncio.run(
            routes["/api/v1/ingestion"].endpoint(IngestionRequestDto(source_id="doc-1"))
        )
        evaluation = asyncio.run(routes["/api/v1/evaluation"].endpoint())
        trace = asyncio.run(routes["/api/v1/traces/{trace_id}"].endpoint("demo-index-active"))

        self.assertEqual(sources["summary"]["source_count"], 35)
        self.assertEqual(diagnosis["status"], "analyzed")
        self.assertEqual(diagnosis["scenario_id"], "inc-ospf-exstart")
        self.assertTrue(device_context["read_only"])
        self.assertEqual(device_context["device_id"], "hw-sz-core-01")
        self.assertEqual(ingestion["status"], "already_indexed")
        self.assertEqual(ingestion["source_id"], "doc-1")
        self.assertEqual(evaluation["status"], "not_run")
        self.assertEqual(evaluation["golden_set"]["case_count"], 50)
        self.assertEqual(trace["trace_id"], "demo-index-active")


if __name__ == "__main__":
    unittest.main()
