from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from deploy.railway import migration_runner


def _read_text(rel_path: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / rel_path).read_text(encoding="utf-8")


def test_api_and_engine_startup_do_not_run_db_migrations() -> None:
    api_start = _read_text("deploy/railway/start_api.sh").lower()
    engine_start = _read_text("deploy/railway/start_engine.sh").lower()

    forbidden_tokens = ("alembic", "upgrade head", "python -m alembic")
    for token in forbidden_tokens:
        assert token not in api_start
        assert token not in engine_start


def test_migration_ownership_stays_in_migrator_service(monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock

    from deploy.railway import migration_runner

    migrator_start = _read_text("deploy/railway/start_migrator.sh").lower()
    assert "python deploy/railway/migration_runner.py" in migrator_start
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(migration_runner.subprocess, "run", run)
    assert migration_runner.run_migrations() == 0
    assert run.call_args.args[0][1:] == ["-m", "alembic", "upgrade", "head"]
    assert run.call_args.kwargs["capture_output"] is True
    assert "redact_sensitive_log_text" in _read_text("deploy/railway/migration_runner.py")


def test_non_migrator_startup_scripts_do_not_run_db_migrations() -> None:
    railway_dir = Path(__file__).resolve().parents[1] / "deploy" / "railway"
    forbidden_tokens = (
        "alembic",
        "upgrade head",
        "python -m alembic",
        "migration_runner",
    )

    for startup_script in sorted(railway_dir.glob("start_*.sh")):
        if startup_script.name == "start_migrator.sh":
            continue
        startup_text = startup_script.read_text(encoding="utf-8").lower()
        for token in forbidden_tokens:
            assert token not in startup_text, (startup_script.name, token)


def test_migration_runner_executes_alembic_fail_closed_and_redacts_output(
    monkeypatch,
    capsys,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, options))
        return subprocess.CompletedProcess(
            command,
            23,
            stdout="DATABASE_URL=postgresql://wolf:supersecret@db.internal:5432/wolf\n",
            stderr="PGPASSWORD=supersecret API_KEY=secret-token redis://cache:redispass@cache.internal:6379/0\n",
        )

    monkeypatch.setattr(migration_runner.subprocess, "run", fake_run)
    assert migration_runner.run_migrations() == 23
    captured = capsys.readouterr()
    assert calls == [
        (
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            {"check": False, "capture_output": True, "text": True},
        )
    ]
    assert "supersecret" not in captured.out
    assert "supersecret" not in captured.err
    assert "secret-token" not in captured.err
    assert "redispass" not in captured.err
    assert "$REDACTED" in captured.out
    assert "$REDACTED" in captured.err
    assert "$CONNECTION_URL" in captured.err
