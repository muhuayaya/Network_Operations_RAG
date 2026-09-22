"""RAG 系统的最小命令行入口。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from netops_copilot import __version__
from netops_copilot.application.demo_runtime import (
    DemoBuildReport,
    DemoRuntimeDependencyError,
    build_demo_runtime,
    load_active_index_descriptor,
)
from netops_copilot.application.doctor import doctor_report
from netops_copilot.application.local_milvus_runtime import (
    LocalMilvusBuildReport,
    build_local_milvus_runtime,
    local_milvus_doctor,
)
from netops_copilot.application.ports.providers import ProviderKind
from netops_copilot.bootstrap import bootstrap, create_builtin_registry
from netops_copilot.interfaces.cli.lifecycle import ingest_dataset, reset_runtime
from netops_copilot.settings import ProfileName


def create_parser() -> argparse.ArgumentParser:
    """构建 CLI 解析器，但不执行应用启动组合。"""
    parser = argparse.ArgumentParser(prog="netops-copilot", description="面向企业IT与网络运维的RAG系统命令行工具")
    _localize_parser_help(parser)
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", title="子命令")
    doctor = subparsers.add_parser("doctor", help="报告依赖就绪状态")
    _localize_parser_help(doctor)
    doctor.add_argument(
        "--profile",
        choices=[profile.value for profile in ProfileName],
        default=ProfileName.DEMO_LITE.value,
    )
    doctor.add_argument("--runtime-dir", type=Path, default=_default_runtime_dir())
    index_build = subparsers.add_parser(
        "index-build",
        help="构建并激活 demo-lite 的 Dense 和 Lexical 索引",
    )
    _localize_parser_help(index_build)
    index_build.add_argument(
        "--profile",
        choices=[profile.value for profile in ProfileName],
        default=ProfileName.DEMO_LITE.value,
    )
    index_build.add_argument("--dataset-root", type=Path, default=_default_dataset_root())
    index_build.add_argument("--runtime-dir", type=Path, default=_default_runtime_dir())
    index_build.add_argument("--version-id", default=None)
    reset = subparsers.add_parser("reset", help="删除生成的演示运行时状态")
    _localize_parser_help(reset)
    reset.add_argument("--runtime-dir", type=Path, default=_default_runtime_dir())
    seed = subparsers.add_parser("seed", help="重新生成固定的合成演示数据")
    _localize_parser_help(seed)
    seed.add_argument("--dataset-root", type=Path, default=_default_dataset_root())
    ingest = subparsers.add_parser("ingest", help="解析演示数据并生成摄取清单")
    _localize_parser_help(ingest)
    ingest.add_argument("--dataset-root", type=Path, default=_default_dataset_root())
    ingest.add_argument("--runtime-dir", type=Path, default=_default_runtime_dir())
    demo = subparsers.add_parser("demo-lite", help="重置、生成并摄取可复现的演示数据")
    _localize_parser_help(demo)
    demo.add_argument("--dataset-root", type=Path, default=_default_dataset_root())
    demo.add_argument("--runtime-dir", type=Path, default=_default_runtime_dir())
    local = subparsers.add_parser("local-milvus", help="执行 local-milvus 就绪检查")
    _localize_parser_help(local)
    local.add_argument("--doctor-only", action="store_true", help="只报告依赖就绪状态")
    return parser


def _localize_parser_help(parser: argparse.ArgumentParser) -> None:
    """将 CLI 帮助标题显示为中文，同时保留命令标识符。"""

    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"


def main() -> None:
    """执行 CLI 命令。"""
    arguments = create_parser().parse_args()
    if arguments.command == "doctor":
        profile = ProfileName(arguments.profile)
        if profile is ProfileName.LOCAL_MILVUS:
            readiness_report = local_milvus_doctor()
        else:
            container = bootstrap(profile)
            registry = create_builtin_registry()
            optional_providers = (
                registry.create(ProviderKind.LLM, "local-reserved", container.settings),
                registry.create(ProviderKind.RERANKER, "local-reserved", container.settings),
            )
            active_index = load_active_index_descriptor(arguments.runtime_dir)
            readiness_report = doctor_report(
                container,
                active_index=active_index,
                optional_providers=optional_providers,
            )
        print(json.dumps(readiness_report.to_dict(), ensure_ascii=False, indent=2))
    elif arguments.command == "index-build":
        profile = ProfileName(arguments.profile)
        build_report: DemoBuildReport | LocalMilvusBuildReport
        try:
            if profile is ProfileName.LOCAL_MILVUS:
                build_report = build_local_milvus_runtime(
                    profile,
                    arguments.dataset_root,
                    arguments.runtime_dir,
                    arguments.version_id,
                )
            else:
                build_report = build_demo_runtime(
                    profile,
                    arguments.dataset_root,
                    arguments.runtime_dir,
                    arguments.version_id,
                )
        except (DemoRuntimeDependencyError, ValueError, RuntimeError) as error:
            print(
                json.dumps(
                    {"status": "error", "profile": profile.value, "error": str(error)},
                    ensure_ascii=False,
                )
            )
            raise SystemExit(1) from error
        print(
            json.dumps(
                    {"status": "ready", "profile": build_report.profile.value, **asdict(build_report)},
                ensure_ascii=False,
            )
        )
    elif arguments.command == "reset":
        reset_runtime(arguments.runtime_dir)
        print(json.dumps({"status": "reset", "runtime_dir": str(arguments.runtime_dir)}, ensure_ascii=False))
    elif arguments.command == "seed":
        generator = _project_root() / "tools" / "generate_demo_dataset.py"
        subprocess.run([sys.executable, str(generator)], cwd=_project_root(), check=True)
        print(json.dumps({"status": "seeded", "dataset_root": str(arguments.dataset_root)}, ensure_ascii=False))
    elif arguments.command == "ingest":
        summary = ingest_dataset(arguments.dataset_root, arguments.runtime_dir)
        print(json.dumps({"status": "ingested", **asdict(summary)}, ensure_ascii=False))
    elif arguments.command == "demo-lite":
        reset_runtime(arguments.runtime_dir)
        generator = _project_root() / "tools" / "generate_demo_dataset.py"
        subprocess.run([sys.executable, str(generator)], cwd=_project_root(), check=True)
        summary = ingest_dataset(arguments.dataset_root, arguments.runtime_dir)
        print(json.dumps({"status": "ready", "profile": "demo-lite", **asdict(summary)}, ensure_ascii=False))
    elif arguments.command == "local-milvus":
        report = local_milvus_doctor()
        print(json.dumps({"status": "ready" if report.status.value == "healthy" else "not_ready", "profile": "local-milvus", **report.to_dict()}, ensure_ascii=False))


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_dataset_root() -> Path:
    return _project_root() / "datasets" / "demo"


def _default_runtime_dir() -> Path:
    return _default_dataset_root() / ".runtime"
