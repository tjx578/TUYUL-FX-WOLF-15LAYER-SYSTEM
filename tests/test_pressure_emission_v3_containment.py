from __future__ import annotations

import ast
from pathlib import Path


def test_p1_modules_do_not_import_downstream_authority() -> None:
    root = Path(__file__).parents[1]
    sources = [
        root / "contracts" / "strategy_5scr_pressure_emission_v3.py",
        *(root / "analysis" / "strategy_5scr_v3" / "pressure").glob("*.py"),
    ]
    forbidden = (
        "risk_reservation",
        "execution_command",
        "mt5_operator_shadow",
        "strategy_5scr_pressure_inbox",
        "strategy_5scr_lifecycle_v2_repository",
        "strategy_5scr_microboost_pulse_engine",
    )

    imported: set[str] = set()
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    assert not any(token in module for module in imported for token in forbidden)


def test_pressure_namespace_has_no_eager_imports() -> None:
    source = Path(__file__).parents[1] / "analysis" / "strategy_5scr_v3" / "pressure" / "__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))


def test_p1_has_no_runtime_consumer() -> None:
    root = Path(__file__).parents[1]
    production = (root / "analysis", root / "services", root / "storage", root / "api", root / "execution")
    consumers: list[str] = []
    for directory in production:
        for source in directory.rglob("*.py"):
            if "strategy_5scr_v3/pressure" in source.as_posix():
                continue
            text = source.read_text(encoding="utf-8")
            if "strategy_5scr_v3.pressure" in text or "CanonicalPressureEmissionV3" in text:
                consumers.append(str(source.relative_to(root)))

    assert consumers == []
