"""Separate seven-case producer/relay gate; never substitutes for consumer acceptance."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.run_pair_activity_runtime_acceptance import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(test_module="tests/integration/test_activity_delivery_producer_postgres.py"))
