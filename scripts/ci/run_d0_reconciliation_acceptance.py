"""Run D0 acceptance in its own guarded disposable PostgreSQL clone.

Governance audit rows are append-only. Preserve them in the child database;
never delete audit rows or relax the clean-target guard to run another suite.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.run_strategy_persistence_acceptance import isolated_domain_database  # noqa: E402
from scripts.ci.validate_suite_junit import validate  # noqa: E402


def main():
    receipt = ROOT / "artifacts/python-suite/d0-reconciliation.xml"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with isolated_domain_database():
        environment = dict(os.environ)
        environment.update(
            DATABASE_URL=environment["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"],
            WOLF15_LOAD_DOTENV="false",
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_broker_reconciliation_evidence.py",
                "tests/test_mt5_engineering_demo_canary.py",
                "tests/integration/test_mt5_engineering_demo_canary_postgres.py",
                "-o",
                "addopts=",
                "-q",
                "--timeout=60",
                f"--junitxml={receipt}",
            ],
            cwd=ROOT,
            env=environment,
            check=True,
            timeout=240,
        )
    print(f"Required D0 cases executed without skip: {validate(receipt)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
