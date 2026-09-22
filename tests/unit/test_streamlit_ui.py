"""不启动 UI 进程即可执行的 Streamlit 页面契约测试。"""

from __future__ import annotations

import unittest

from netops_copilot.interfaces.ui import PAGE_NAMES, PageServices


class StreamlitUiTests(unittest.TestCase):
    def test_four_application_pages_are_named_and_services_are_injected(self) -> None:
        self.assertEqual(
            PAGE_NAMES,
            ("知识检索", "事故场景回放", "配置差异比较", "追踪与评测"),
        )
        services = PageServices(knowledge_query=lambda query: {"query": query})
        self.assertEqual(services.knowledge_query("OSPF"), {"query": "OSPF"})


if __name__ == "__main__":
    unittest.main()
