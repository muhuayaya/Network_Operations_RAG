"""拒绝领域层和应用层导入框架或 SDK。"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

FORBIDDEN_TOP_LEVEL_MODULES = frozenset(
    {"chromadb", "fastapi", "mcp", "openai", "pymilvus", "streamlit"}
)
PROTECTED_LAYERS = ("application", "domain")


def find_violations(package_root: Path) -> list[str]:
    """返回受保护层中发现的禁用导入。"""
    violations: list[str] = []
    for layer in PROTECTED_LAYERS:
        for path in sorted((package_root / layer).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported_names: list[str] = []
                if isinstance(node, ast.Import):
                    imported_names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_names = [node.module]
                for name in imported_names:
                    if name.split(".", maxsplit=1)[0] in FORBIDDEN_TOP_LEVEL_MODULES:
                        violations.append(f"{path}: forbidden import {name}")
    return violations


def main() -> int:
    """检查本仓库的受保护层。"""
    package_root = Path(__file__).resolve().parents[1] / "src" / "netops_copilot"
    violations = find_violations(package_root)
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
