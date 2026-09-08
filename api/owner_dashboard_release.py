"""Fail-closed process entrypoint for the owner dashboard API release."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

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

ATTESTED_SOURCE_PATHS = (
    "api/owner_dashboard_release.py",
    "api/app_factory.py",
    "deploy/railway/owner-dashboard-api.json",
    "deploy/railway/start_api.sh",
)


def emit_startup_attestation(background_started: Mapping[str, bool]) -> None:
    """Emit a fixed, credential-free startup receipt from the actual API worker."""
    validate_release_environment(os.environ)
    if os.environ.get("WOLF15_API_READ_ONLY_STARTUP") != "true" or os.environ.get("WOLF15_SERVICE_ROLE") != "api":
        raise ValueError("Owner dashboard startup profile is not active")
    if set(background_started) != {"outbox", "relay", "peer_health", "candle_aggregator", "orchestrator"} or any(
        background_started.values()
    ):
        raise ValueError("Owner dashboard background containment failed")
    root = Path(__file__).resolve().parents[1]
    receipt = {
        "schema": "owner-dashboard-startup-v1",
        "pid": os.getpid(),
        "read_only_startup": True,
        "role_api": True,
        "disabled_flags": {name: os.environ.get(name) == "false" for name in DISABLED_FLAGS},
        "background_started": dict(background_started),
        "files": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ATTESTED_SOURCE_PATHS},
    }
    if not all(receipt["disabled_flags"].values()):
        raise ValueError("Owner dashboard flags are not normalized")
    print("WOLF15_OWNER_STARTUP_ATTESTATION " + json.dumps(receipt, sort_keys=True), flush=True)


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
