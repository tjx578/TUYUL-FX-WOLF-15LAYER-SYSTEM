"""Preserve an existing TEST_ONLY capacity ledger across the supported 05->head upgrade."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from contracts.strategy_5scr_capacity_owner_v31 import CapacityOwnerFenceV31  # noqa: E402
from scripts.ci.pair_activity_run_evidence import migration_graph, observe_postgres, redact  # noqa: E402
from scripts.ci.run_strategy_persistence_acceptance import isolated_domain_database  # noqa: E402
from storage.strategy_5scr_capacity_v31 import CapacityRepositoryV31  # noqa: E402
from tests.integration.test_candidate_revision_v31_postgres import DB  # noqa: E402
from tests.test_strategy_5scr_candidate_handoff_v31 import bundle  # noqa: E402


def main():
    folder = ROOT / "artifacts/pair-activity-runtime/supported-upgrade"
    folder.mkdir(parents=True, exist_ok=False)
    receipt = {
        "scope": "DISPOSABLE_05_TO_HEAD_EXISTING_TEST_ONLY_CAPACITY_LEDGER",
        "accepted": False,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "steps": [],
    }
    try:
        with isolated_domain_database(empty=True) as database:
            env = dict(os.environ)
            env.update(DATABASE_URL=env["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"], WOLF15_LOAD_DOTENV="false")
            receipt["database"] = database
            expected_head = migration_graph(ROOT)["repository_heads"][0]

            def migrate(target):
                result = subprocess.run(
                    [sys.executable, "-m", "alembic", "upgrade", target],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                (folder / f"upgrade-{target}.log").write_text(
                    redact(result.stdout + result.stderr, env), encoding="utf-8"
                )
                receipt["steps"].append({"target": target, "exit_code": result.returncode})
                if result.returncode:
                    raise ValueError("MIGRATION_SUBPROCESS_FAILED")

            migrate("20260909_05")
            ledger, _, _ = bundle()
            fence = CapacityOwnerFenceV31(
                profile="TEST_ONLY",
                account_id=ledger.account_id,
                executor_id=ledger.executor_id,
                owner_id="upgrade-fixture-owner",
                owner_epoch=1,
                token=uuid4(),
            )

            async def state(initialize):
                async with DB(env["DATABASE_URL"]).transaction() as connection:
                    repository = CapacityRepositoryV31(fence=fence)
                    if initialize:
                        await repository.initialize_in_transaction(connection, ledger, verify_initial=lambda *_: True)
                    loaded = await repository.lock_current(connection)
                    assert loaded == ledger
                    row = await connection.fetchrow(
                        "SELECT * FROM public.strategy_5scr_capacity_ledgers_v31 WHERE account_id=$1", ledger.account_id
                    )
                    return hashlib.sha256(json.dumps(dict(row), sort_keys=True, default=str).encode()).hexdigest()

            receipt["baseline_row_hash"] = asyncio.run(state(True))
            with psycopg.connect(env["DATABASE_URL"]) as connection:
                assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "20260909_05"
                assert (
                    connection.execute(
                        "SELECT to_regclass('public.strategy_5scr_transaction_a_outbox_v31')"
                    ).fetchone()[0]
                    is None
                )
            migrate("head")
            receipt["upgraded_row_hash"] = asyncio.run(state(False))
            assert receipt["baseline_row_hash"] == receipt["upgraded_row_hash"]
            with psycopg.connect(env["DATABASE_URL"]) as connection:
                receipt["postgres"] = observe_postgres(connection, database, expected_head, 16)
                for name in ("campaigns", "parent_legs", "signal_previews", "outbox"):
                    assert connection.execute(
                        "SELECT to_regclass(%s)", (f"public.strategy_5scr_transaction_a_{name}_v31",)
                    ).fetchone()[0]
            receipt["accepted"] = True
    except Exception as exc:
        receipt["failure_class"] = type(exc).__name__
    finally:
        (folder / "upgrade-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"supported_upgrade_accepted": receipt["accepted"], "source_commit": receipt["source_commit"]}))
    return 0 if receipt["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
