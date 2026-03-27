"""Architectural isolation tests for trq/accounts/execution boundaries."""

from pathlib import Path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def test_trq_does_not_import_accounts() -> None:
    trq_dir = Path(__file__).parents[2] / "trq"
    if not trq_dir.exists():
        return

    for py_file in trq_dir.glob("*.py"):
        content = _read(py_file)
        assert "from accounts" not in content
        assert "import accounts" not in content


def test_accounts_does_not_import_trq() -> None:
    accounts_dir = Path(__file__).parents[2] / "accounts"
    for py_file in accounts_dir.glob("*.py"):
        content = _read(py_file)
        assert "from trq" not in content
        assert "import trq" not in content


def test_execution_does_not_import_trq() -> None:
    execution_dir = Path(__file__).parents[2] / "execution"
    for py_file in execution_dir.glob("*.py"):
        content = _read(py_file)
        assert "from trq" not in content
        assert "import trq" not in content
