"""Derive a scoped MT5 executor token from the bridge master secret."""

from __future__ import annotations

import argparse
import os
from uuid import UUID

from api.middleware.executor_auth import derive_executor_token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executor_id", type=UUID, help="Pre-provisioned EDUMB agent UUID")
    args = parser.parse_args()
    secret = os.getenv("EXECUTOR_BRIDGE_AUTH_SECRET", "").strip()
    if not secret:
        parser.error("EXECUTOR_BRIDGE_AUTH_SECRET is not configured")
    print(derive_executor_token(str(args.executor_id), secret=secret))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
