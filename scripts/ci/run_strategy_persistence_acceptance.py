"""Execute candidate, capacity and TEST_ONLY Transaction A as distinct PG gates."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.run_pair_activity_runtime_acceptance import DOMAIN_TESTS, main  # noqa: E402

if __name__ == "__main__":
    outcomes = [main(test_module=module) for module in DOMAIN_TESTS]
    raise SystemExit(1 if any(outcomes) else 0)
