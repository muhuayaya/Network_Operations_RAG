"""使用显式注入的应用服务启动 demo-lite Streamlit 控制台。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from netops_copilot.application.demo_runtime import (
    build_demo_runtime,
    create_demo_services,
    load_active_index_descriptor,
)
from netops_copilot.interfaces.ui import render
from netops_copilot.settings import ProfileName


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("--profile", choices=[item.value for item in ProfileName], default="demo-lite")
    parser.add_argument("--dataset-root", type=Path, default=_project_root() / "datasets" / "demo")
    parser.add_argument("--runtime-dir", type=Path, default=_project_root() / "datasets" / "demo" / ".runtime")
    parser.add_argument("--build", action="store_true", help="渲染页面前构建新索引")
    arguments = parser.parse_args(_streamlit_arguments())
    profile = ProfileName(arguments.profile)
    if profile is not ProfileName.DEMO_LITE:
        raise SystemExit("run_demo_streamlit 当前仅支持 --profile demo-lite")
    try:
        if arguments.build:
            build_demo_runtime(profile, arguments.dataset_root, arguments.runtime_dir)
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    if load_active_index_descriptor(arguments.runtime_dir) is None:
        raise SystemExit(
            "no active demo index found; run "
            "`uv run --extra demo-index netops-copilot index-build --profile demo-lite` first"
        )
    try:
        render(create_demo_services(profile, arguments.runtime_dir))
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error


def _streamlit_arguments() -> list[str]:
    """返回 Streamlit 的 ``--`` 分隔符之后的参数。"""
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    main()
