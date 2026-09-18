"""Regression coverage for static retired-shim imports, including package relatives."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.check_deprecated_imports import check_imports

GUARD = Path(__file__).resolve().parents[1] / "scripts/ci/check_deprecated_imports.py"


def _write(root: Path, name: str, source: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("api/routes.py", "import dashboard.price_feed"),
        ("api/routes.py", "import dashboard.trade_ledger as ledger"),
        ("api/routes.py", "import dashboard.price_feed.client as client"),
        ("api/routes.py", "from dashboard import price_feed as feed"),
        ("api/routes.py", "from dashboard.trade_ledger import record"),
        ("api/routes.py", "from dashboard.price_feed.client import fetch"),
        ("dashboard/router.py", "from . import price_feed"),
        ("dashboard/__init__.py", "from . import trade_ledger as ledger"),
        ("dashboard/router.py", "from .price_feed import fetch"),
        ("dashboard/router.py", "from .trade_ledger import *"),
        ("dashboard/nested/router.py", "from .. import price_feed as feed"),
        ("dashboard/nested/__init__.py", "from ..trade_ledger import record"),
        ("dashboard/nested/deeper/router.py", "from ...price_feed.client import fetch"),
    ],
)
def test_retired_absolute_and_relative_imports_fail(tmp_path: Path, capsys, name: str, source: str):
    _write(tmp_path, name, "# fixture\n" + source + "\n")
    assert check_imports(tmp_path, [name]) == 1
    assert f"::error file={name},line=2::Deprecated dashboard import" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("api/routes.py", "from storage import price_feed, trade_ledger"),
        ("api/routes.py", "import dashboard.price_feed_tools"),
        ("api/routes.py", "from dashboard import trade_ledger_tools"),
        ("dashboard/router.py", "from . import current_price_feed"),
        ("dashboard/nested/router.py", "from . import price_feed"),
        ("services/dashboard/router.py", "from .trade_ledger import record"),
        ("services/nested/router.py", "from .. import price_feed"),
        ("dashboard/router.py", "from ..dashboard import price_feed"),
        ("router.py", "from . import price_feed"),
        ("api/routes.py", "message = 'from dashboard import price_feed'"),
    ],
)
def test_unrelated_names_and_invalid_relatives_are_not_misclassified(tmp_path: Path, capsys, name: str, source: str):
    _write(tmp_path, name, source + "\n")
    assert check_imports(tmp_path, [name]) == 0
    assert capsys.readouterr().out == ""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _run_guard(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(GUARD)], cwd=root, capture_output=True, text=True, timeout=30)


def test_cli_rejects_tracked_relative_import(tmp_path: Path):
    _git(tmp_path, "init")
    _write(tmp_path, "dashboard/nested/__init__.py", "from .. import price_feed\n")
    _git(tmp_path, "add", "dashboard")
    result = _run_guard(tmp_path)
    assert result.returncode == 1
    assert "file=dashboard/nested/__init__.py,line=1" in result.stdout


def test_cli_syntax_failure_does_not_hide_other_imports(tmp_path: Path):
    _git(tmp_path, "init")
    _write(tmp_path, "a_bad_syntax.py", "def broken(:\n")
    _write(tmp_path, "dashboard/routes.py", "from . import trade_ledger\n")
    _git(tmp_path, "add", ".")
    result = _run_guard(tmp_path)
    assert result.returncode == 1
    assert "Python syntax error prevents import inspection" in result.stdout
    assert "file=dashboard/routes.py,line=1::Deprecated dashboard import" in result.stdout


def test_cli_preserves_tracked_python_scope_and_nested_exclusions(tmp_path: Path):
    _git(tmp_path, "init")
    _write(tmp_path, "dashboard/routes.py", "from storage import price_feed\n")
    for name in (
        "tests/example.py",
        "package/tests/example.py",
        "package/__pycache__/example.py",
        "package/.venv/example.py",
        "package/node_modules/example.py",
        "example.txt",
    ):
        _write(tmp_path, name, "from dashboard import price_feed\n")
    _git(tmp_path, "add", ".")
    _write(tmp_path, "untracked.py", "from dashboard import price_feed\n")
    result = _run_guard(tmp_path)
    assert result.returncode == 0
    assert result.stdout == ""


def test_cli_git_inspection_failure_is_not_success(tmp_path: Path):
    result = _run_guard(tmp_path)
    assert result.returncode != 0
