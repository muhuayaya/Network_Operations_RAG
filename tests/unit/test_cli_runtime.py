"""真实 demo-lite 运行时 CLI 入口覆盖测试。"""

from __future__ import annotations

import unittest

from netops_copilot.interfaces.cli.main import create_parser


class CliRuntimeTests(unittest.TestCase):
    def test_index_build_command_exposes_runtime_paths_and_version(self) -> None:
        arguments = create_parser().parse_args(
            [
                "index-build",
                "--profile",
                "demo-lite",
                "--dataset-root",
                "datasets/demo",
                "--runtime-dir",
                "datasets/demo/.runtime",
                "--version-id",
                "test-version",
            ]
        )
        self.assertEqual(arguments.command, "index-build")
        self.assertEqual(arguments.profile, "demo-lite")
        self.assertEqual(arguments.version_id, "test-version")


if __name__ == "__main__":
    unittest.main()
