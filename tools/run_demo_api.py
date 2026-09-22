"""使用显式注入的运行时启动 demo-lite FastAPI 应用。"""

from __future__ import annotations

import argparse
from pathlib import Path

from netops_copilot.application.demo_runtime import (
    build_demo_runtime,
    create_demo_services,
    load_active_index_descriptor,
)
from netops_copilot.interfaces.api import create_app_from_services
from netops_copilot.settings import ProfileName


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("--profile", choices=[item.value for item in ProfileName], default="demo-lite")
    parser.add_argument("--dataset-root", type=Path, default=_project_root() / "datasets" / "demo")
    parser.add_argument("--runtime-dir", type=Path, default=_project_root() / "datasets" / "demo" / ".runtime")
    parser.add_argument("--build", action="store_true", help="启动服务前构建新索引")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    profile = ProfileName(arguments.profile)
    if profile is not ProfileName.DEMO_LITE:
        raise SystemExit("run_demo_api 当前仅支持 --profile demo-lite")
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
        import uvicorn
    except ImportError as error:
        raise SystemExit("请使用 `uv run --with uvicorn ...` 安装可选的 API 运行器") from error
    try:
        services = create_demo_services(
            profile,
            arguments.runtime_dir,
            dataset_root=arguments.dataset_root,
        )
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    app = create_app_from_services(services)
    uvicorn.run(app, host=arguments.host, port=arguments.port)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    main()
