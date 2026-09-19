"""Natural V2/V31 sizing uses broker-native tick economics, never the legacy static pip-value table."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRST_PARTY = {"analysis", "contracts", "storage", "risk", "config", "core", "execution", "accounts", "schemas"}
NATURAL_ROOTS = (
    "analysis.strategy_5scr_candidate_c2_shadow_v2",
    "storage.strategy_5scr_candidate_c2_shadow_v2_repository",
    "risk.strategy_5scr_candidate_handoff_v31",
    "risk.strategy_5scr_capacity_v31",
    "storage.strategy_5scr_candidate_revision_v31",
    "storage.strategy_5scr_capacity_v31",
    "storage.strategy_5scr_transaction_a_v31",
)


def _source(module: str) -> Path | None:
    base = ROOT.joinpath(*module.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.exists():
            return path
    return None


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def test_natural_sizing_graph_never_imports_pip_value_table():
    seen: set[str] = set()
    stack: list[str] = list(NATURAL_ROOTS)
    offenders: list[tuple[str, str]] = []
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _source(module)
        if path is None:
            continue
        for imported in _imports(path):
            if imported == "config.pip_values" or imported.startswith("config.pip_values."):
                offenders.append((module, imported))
            if imported.split(".")[0] in FIRST_PARTY:
                stack.append(imported)
    assert all(_source(root) is not None for root in NATURAL_ROOTS)
    assert offenders == []


def test_c2_shadow_v2_sizes_from_broker_tick_economics():
    source = (ROOT / "analysis" / "strategy_5scr_candidate_c2_shadow_v2.py").read_text(encoding="utf-8")
    assert "tick_value_loss" in source and "tick_size" in source
    assert "pip_value" not in source
