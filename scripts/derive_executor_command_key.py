"""Derive one MT5 executor's scoped command-verification key."""

from __future__ import annotations

import argparse
import os
from uuid import UUID

from contracts.mt5_execution_protocol import derive_executor_command_verification_key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executor_id", type=UUID, help="Pre-provisioned EDUMB agent UUID")
    args = parser.parse_args()
    root_secret = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET", "").strip()
    if not root_secret:
        parser.error("EXECUTOR_COMMAND_SIGNING_SECRET is not configured")
    key = derive_executor_command_verification_key(args.executor_id, root_secret=root_secret)
    print("hex:" + key.hex())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
