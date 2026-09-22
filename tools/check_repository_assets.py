"""确保仓库只包含产品、测试、评测和运维资产。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ALLOWED_TOP_LEVEL_PATHS = frozenset(
    {
        ".github",
        "config",
        "datasets",
        "evals",
        "ops",
        "reports",
        "src",
        "tests",
        "tools",
    }
)
ALLOWED_ROOT_FILES = frozenset(
    {
        "README.md",
        ".env",
        ".gitignore",
        "docker-compose.yml",
        "pyproject.toml",
        "uv.lock",
        "部署与操作手册.md",
    }
)
IGNORED_TOP_LEVEL_PATHS = frozenset(
    {
        ".git",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
    }
)
FORBIDDEN_ASSET_PATTERNS = (
    re.compile(r"(?:^|/)skills?/(?:[^/]+/)*[^/]+$"),
    re.compile(r"(?:^|/)(?:training|study)[_-]?(?:report|notes?)(?:\.[^/]+)?$"),
    re.compile(r"(?:^|/)(?:personal|profile-)[^/]*(?:\.[^/]+)?$"),
    re.compile(r"(?:^|/)(?:question-bank|lesson)[^/]*(?:\.[^/]+)?$"),
    re.compile(r"(?:^|/)guide[^/]*\.pdf$"),
)


def find_asset_policy_violations(repository_root: Path) -> list[str]:
    """返回不在产品资产允许列表中或匹配禁用内容的路径。"""
    violations: list[str] = []
    for path in sorted(repository_root.rglob("*")):
        relative = path.relative_to(repository_root)
        if not relative.parts or relative.parts[0] in IGNORED_TOP_LEVEL_PATHS:
            continue
        normalized = relative.as_posix().lower()
        if any(pattern.search(normalized) for pattern in FORBIDDEN_ASSET_PATTERNS):
            violations.append(f"forbidden asset category: {relative.as_posix()}")
            continue
        if len(relative.parts) == 1 and path.is_file():
            if relative.name not in ALLOWED_ROOT_FILES:
                violations.append(f"unallowlisted root file: {relative.as_posix()}")
        elif relative.parts[0] not in ALLOWED_TOP_LEVEL_PATHS and path.is_file():
            violations.append(f"unallowlisted top-level path: {relative.as_posix()}")
    return violations


def main() -> int:
    """校验本仓库中的资产。"""
    root = Path(__file__).resolve().parents[1]
    violations = find_asset_policy_violations(root)
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
