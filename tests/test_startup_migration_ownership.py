from __future__ import annotations

from pathlib import Path


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


def test_migration_ownership_stays_in_migrator_service() -> None:
    migrator_start = _read_text("deploy/railway/start_migrator.sh").lower()

    assert "python -m alembic upgrade head" in migrator_start
