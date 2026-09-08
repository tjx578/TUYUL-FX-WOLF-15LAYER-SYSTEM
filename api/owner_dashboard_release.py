"""Fail-closed process entrypoint for the owner dashboard API release."""

from __future__ import annotations

import base64
import os
import sys
from collections.abc import Mapping

DISABLED_FLAGS = (
    "WOLF15_EMBED_ORCHESTRATOR",
    "ALLOW_DASHBOARD_WRITE",
    "ALLOW_MARKET_EXECUTION",
    "EXECUTION_ENABLED",
    "MT5_ORDER_SEND_ENABLED",
    "EA_COMMAND_DELIVERY_ENABLED",
    "EXECUTION_COMMAND_PRODUCER_ENABLED",
    "LEGACY_PUSH_EXECUTION_ENABLED",
    "SIGNED_COMMAND_BRIDGE_ENABLED",
    "TRADE_OUTBOX_WRITE_ENABLED",
    "RISK_RESERVATION_ENABLED",
    "STRATEGY_5SCR_EXECUTION_ENABLED",
    "CANARY_ISSUANCE_ENABLED",
    "ENABLE_DEV_ROUTES",
)


def validate_release_environment(env: Mapping[str, str]) -> None:
    """Inspect only; errors identify keys, never their values."""
    for name in DISABLED_FLAGS:
        if env.get(name, "false").strip().lower() not in {"false", "0", "no", "off"}:
            raise ValueError(f"Owner dashboard release requires {name}=false")
    if not env.get("DASHBOARD_OWNER_USERNAME", "").strip():
        raise ValueError("DASHBOARD_OWNER_USERNAME is required")
    encoded = env.get("DASHBOARD_OWNER_PASSWORD_HASH", "").strip()
    try:
        algorithm, iterations, salt, digest = encoded.split("$")
        salt_bytes = base64.b64decode(salt + "=" * (-len(salt) % 4), altchars=b"-_", validate=True)
        digest_bytes = base64.b64decode(digest + "=" * (-len(digest) % 4), altchars=b"-_", validate=True)
        if (
            algorithm != "pbkdf2_sha256"
            or not 210_000 <= int(iterations) <= 2_000_000
            or len(encoded) > 256
            or len(salt_bytes) < 16
            or len(digest_bytes) != 32
        ):
            raise ValueError("Invalid verifier")
    except ValueError:
        raise ValueError("A valid DASHBOARD_OWNER_PASSWORD_HASH is required") from None
    secret = env.get("DASHBOARD_JWT_SECRET", "").strip()
    if len(secret) < 32:
        raise ValueError("A strong DASHBOARD_JWT_SECRET is required")


def main() -> int:
    try:
        validate_release_environment(os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 78
    for name in DISABLED_FLAGS:
        os.environ[name] = "false"
    os.environ["WOLF15_API_READ_ONLY_STARTUP"] = "true"
    os.environ["WOLF15_SERVICE_ROLE"] = "api"
    os.execvp("bash", ["bash", "deploy/railway/start_api.sh"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
