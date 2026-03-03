"""Architectural isolation tests for engine/accounts/execution boundaries."""

from pathlib import Path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def test_engine_does_not_import_accounts() -> None:
    engine_dir = Path(__file__).parents[2] / "engine"
    if not engine_dir.exists():
        return

    for py_file in engine_dir.glob("*.py"):
        content = _read(py_file)
        assert "from accounts" not in content
        assert "import accounts" not in content


def test_accounts_does_not_import_engine() -> None:
    accounts_dir = Path(__file__).parents[2] / "accounts"
    for py_file in accounts_dir.glob("*.py"):
        content = _read(py_file)
        assert "from engine" not in content
        assert "import engine" not in content


def test_execution_does_not_import_engine() -> None:
    execution_dir = Path(__file__).parents[2] / "execution"
    for py_file in execution_dir.glob("*.py"):
        content = _read(py_file)
        assert "from engine" not in content
        assert "import engine" not in content
