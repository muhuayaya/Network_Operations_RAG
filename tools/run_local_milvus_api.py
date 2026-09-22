"""启动使用真实 Milvus/PostgreSQL 后端的 local-milvus FastAPI 服务。"""

from __future__ import annotations

import argparse
from pathlib import Path

from netops_copilot.application.local_milvus_runtime import (
    build_local_milvus_runtime,
    create_local_milvus_services,
)
from netops_copilot.interfaces.api import create_app_from_services
from netops_copilot.settings import ProfileName


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=_project_root() / "datasets" / "demo")
    parser.add_argument("--runtime-dir", type=Path, default=_project_root() / "datasets" / "demo" / ".runtime")
    parser.add_argument("--build", action="store_true", help="启动服务前构建并激活新索引")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    try:
        if arguments.build:
            build_local_milvus_runtime(
                ProfileName.LOCAL_MILVUS,
                arguments.dataset_root,
                arguments.runtime_dir,
            )
        services = create_local_milvus_services(ProfileName.LOCAL_MILVUS, arguments.runtime_dir)
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    try:
        import uvicorn
    except ImportError as error:
        raise SystemExit("请使用 `uv run --extra local-milvus --with uvicorn ...` 安装 API 运行器") from error
    uvicorn.run(create_app_from_services(services), host=arguments.host, port=arguments.port)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    main()
