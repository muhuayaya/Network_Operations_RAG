"""启动使用真实 Milvus/PostgreSQL 后端的 local-milvus Streamlit 控制台。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from netops_copilot.application.local_milvus_runtime import (
    build_local_milvus_runtime,
    create_local_milvus_services,
)
from netops_copilot.interfaces.ui import render
from netops_copilot.settings import ProfileName


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=_project_root() / "datasets" / "demo")
    parser.add_argument("--runtime-dir", type=Path, default=_project_root() / "datasets" / "demo" / ".runtime")
    parser.add_argument("--build", action="store_true", help="渲染页面前构建并激活新索引")
    arguments = parser.parse_args(_streamlit_arguments())
    try:
        if arguments.build:
            build_local_milvus_runtime(
                ProfileName.LOCAL_MILVUS,
                arguments.dataset_root,
                arguments.runtime_dir,
            )
        render(create_local_milvus_services(ProfileName.LOCAL_MILVUS, arguments.runtime_dir))
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error


def _streamlit_arguments() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    main()
