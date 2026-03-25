"""PR-003 regression tests — backend must not import from dashboard namespace.

Tests verify:
  1. Canonical modules exist and export expected classes
  2. Dashboard shims re-export correctly (backward compat)
  3. API routers import from canonical backend domains, NOT dashboard.*
  4. Boundary scan: no api/ file imports from dashboard.{account_manager,price_feed,trade_ledger}
"""

from __future__ import annotations

import ast
import importlib
import pathlib

# ── 1. Canonical module existence & exports ──────────────────────────────────


class TestCanonicalModulesExist:
    def test_accounts_account_manager_importable(self) -> None:
        mod = importlib.import_module("accounts.account_manager")
        assert hasattr(mod, "AccountManager")

    def test_storage_price_feed_importable(self) -> None:
        mod = importlib.import_module("storage.price_feed")
        assert hasattr(mod, "PriceFeed")

    def test_storage_trade_ledger_importable(self) -> None:
        mod = importlib.import_module("storage.trade_ledger")
        assert hasattr(mod, "TradeLedger")


# ── 2. Dashboard shims re-export correctly ───────────────────────────────────


class TestDashboardShimsReExport:
    def test_dashboard_account_manager_shim(self) -> None:
        from accounts.account_manager import AccountManager as Canonical
        from dashboard.account_manager import AccountManager as Shim

        assert Shim is Canonical

    def test_dashboard_price_feed_shim(self) -> None:
        from dashboard.price_feed import PriceFeed as Shim
        from storage.price_feed import PriceFeed as Canonical

        assert Shim is Canonical

    def test_dashboard_trade_ledger_shim(self) -> None:
        from dashboard.trade_ledger import TradeLedger as Shim
        from storage.trade_ledger import TradeLedger as Canonical

        assert Shim is Canonical


# ── 3. Router import sources ─────────────────────────────────────────────────


def _get_imports(filepath: pathlib.Path) -> list[str]:
    """Parse a Python file and return all 'from X import ...' module strings."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DASHBOARD_MODULES = {
    "dashboard.account_manager",
    "dashboard.price_feed",
    "dashboard.trade_ledger",
}


class TestRouterImportSources:
    def test_accounts_router_no_dashboard_import(self) -> None:
        imports = _get_imports(_REPO_ROOT / "api" / "accounts_router.py")
        violations = [m for m in imports if m in _DASHBOARD_MODULES]
        assert violations == [], f"accounts_router.py still imports from dashboard: {violations}"

    def test_trades_router_no_dashboard_import(self) -> None:
        imports = _get_imports(_REPO_ROOT / "api" / "trades_router.py")
        violations = [m for m in imports if m in _DASHBOARD_MODULES]
        assert violations == [], f"trades_router.py still imports from dashboard: {violations}"

    def test_ws_routes_no_dashboard_import(self) -> None:
        imports = _get_imports(_REPO_ROOT / "api" / "ws_routes.py")
        violations = [m for m in imports if m in _DASHBOARD_MODULES]
        assert violations == [], f"ws_routes.py still imports from dashboard: {violations}"

    def test_dashboard_routes_no_dashboard_import(self) -> None:
        imports = _get_imports(_REPO_ROOT / "api" / "dashboard_routes.py")
        violations = [m for m in imports if m in _DASHBOARD_MODULES]
        assert violations == [], f"dashboard_routes.py still imports from dashboard: {violations}"


# ── 4. Boundary scan — no api/*.py imports dashboard read models ─────────────


class TestBoundaryScan:
    def test_no_api_file_imports_dashboard_read_models(self) -> None:
        api_dir = _REPO_ROOT / "api"
        violations: list[str] = []
        for py_file in sorted(api_dir.glob("*.py")):
            imports = _get_imports(py_file)
            bad = [m for m in imports if m in _DASHBOARD_MODULES]
            if bad:
                violations.append(f"{py_file.name}: {bad}")
        assert violations == [], "api/ files still import dashboard read models:\n" + "\n".join(violations)
