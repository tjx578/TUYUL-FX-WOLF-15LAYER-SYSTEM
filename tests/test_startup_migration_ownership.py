from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from deploy.railway import migration_runner


def _read_text(rel_path: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / rel_path).read_text(encoding="utf-8")


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
