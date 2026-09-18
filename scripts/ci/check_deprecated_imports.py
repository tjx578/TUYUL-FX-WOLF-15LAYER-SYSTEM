"""Reject static imports of retired dashboard shims in tracked production Python."""

import ast
import subprocess
from collections.abc import Iterable
from importlib.util import resolve_name
from pathlib import Path

RETIRED_MODULES = frozenset({"dashboard.price_feed", "dashboard.trade_ledger"})
EXCLUDED_PARTS = frozenset({"tests", "__pycache__", ".venv", "node_modules"})


def imported_modules(node: ast.Import | ast.ImportFrom, path: Path) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    module = node.module or ""
    if node.level:
        # Both modules and __init__.py belong to the package at their parent path.
        # Resolve names only; inspecting imports must never execute application code.
        package = ".".join(path.parent.parts)
        try:
            module = resolve_name("." * node.level + module, package)
        except (ImportError, ValueError):
            # Invalid relative imports cannot resolve to a retired absolute module.
            return []
    return [module, *(f"{module}.{alias.name}" for alias in node.names)]


def check_imports(root: Path, names: Iterable[str]) -> int:
    failed = False
    for name in names:
        path = Path(name)
        if not name or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        try:
            tree = ast.parse((root / path).read_bytes(), filename=name)
        except SyntaxError:
            print(f"::error file={name}::Python syntax error prevents import inspection")
            failed = True
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if any(
                module == old or module.startswith(old + ".")
                for module in imported_modules(node, path)
                for old in RETIRED_MODULES
            ):
                print(f"::error file={name},line={node.lineno}::Deprecated dashboard import; use storage instead")
                failed = True
    return 1 if failed else 0


def main() -> int:
    root = Path.cwd()
    paths = subprocess.check_output(["git", "ls-files", "-z", "*.py"], cwd=root).decode().split("\0")
    return check_imports(root, paths)


if __name__ == "__main__":
    raise SystemExit(main())
