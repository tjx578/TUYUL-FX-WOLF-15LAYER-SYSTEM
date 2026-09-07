from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deploy.railway import migration_runner


def _read_text(rel_path: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / rel_path).read_text(encoding="utf-8")


def test_api_and_engine_startup_do_not_run_db_migrations() -> None:
    api_start = _read_text("deploy/railway/start_api.sh").lower()
    engine_start = _read_text("deploy/railway/start_engine.sh").lower()

    forbidden_tokens = ("alembic", "upgrade head", "python -m alembic", "migration_runner.py")
    for token in forbidden_tokens:
        assert token not in api_start
        assert token not in engine_start


def test_migration_ownership_stays_in_migrator_service() -> None:
    migrator_start = _read_text("deploy/railway/start_migrator.sh").lower()

    assert "python deploy/railway/migration_runner.py" in migrator_start
    assert "python -m alembic upgrade head" not in migrator_start


def test_migration_runner_default_argv_redacts_output_and_propagates_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}
    database_url = "postgresql://wolf:do-not-print@db.invalid:5432/wolf"

    def _run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=23,
            stdout=f"migration failed DATABASE_URL={database_url}\n",
            stderr="PGPASSWORD=do-not-print\n",
        )

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(migration_runner.sys, "executable", "/opt/wolf15/python")
    monkeypatch.setattr(migration_runner.subprocess, "run", _run)

    result = migration_runner.run_migrations()
    output = capsys.readouterr()

    assert captured["command"] == ["/opt/wolf15/python", "-m", "alembic", "upgrade", "head"]
    assert captured["kwargs"] == {"check": False, "capture_output": True, "text": True}
    assert result == 23
    assert "do-not-print" not in output.out + output.err
    assert "postgresql://" not in output.out + output.err
    assert "DATABASE_URL=$REDACTED" in output.out
    assert "PGPASSWORD=$REDACTED" in output.err


def test_migration_runner_main_returns_failure_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migration_runner, "run_migrations", lambda: 17)

    assert migration_runner.main() == 17
