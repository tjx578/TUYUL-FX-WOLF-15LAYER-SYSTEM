"""
AuthorizedOrderIntent — Blueprint v2 P0 Contract
==================================================
Tamper-evident order intent emitted by Layer-12 Authority.

Execution workers MUST:
  1. Verify ``authority_signature`` using the shared authority secret.
  2. Reject if ``expires_at`` is in the past.
  3. Reject if ``verdict`` is not ``EXECUTE_BUY`` / ``EXECUTE_SELL``.
  4. Never mutate the intent (no lot upsizing, no direction change).

Constitutional invariants:
  - L12 signal MUST NOT carry account state (balance/equity/margin).
    Sizing fields (``lot_size``, ``risk_usd``) are populated by the risk
    plane BEFORE the intent is signed; they reflect a decision already
    ratified, not an L12 computation over account state.
  - Signature is computed over a canonical JSON projection that EXCLUDES
    ``authority_signature`` itself, so tampering with any other field
    invalidates the HMAC.

Key management:
  - Secret is sourced from ``WOLF_AUTHORITY_SECRET`` env var by default.
  - Callers MAY pass an explicit secret (e.g. fetched from KMS/HSM) via
    :func:`sign_intent` / :func:`verify_intent_signature`.
  - This module does NOT generate or rotate secrets — that is the job of
    the key-management layer (out of scope for P0).

Zone: contracts — signing is a boundary concern, not market logic.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "authorized_order_intent.v2"

AUTHORITY_SECRET_ENV = "WOLF_AUTHORITY_SECRET"

Verdict = Literal["EXECUTE_BUY", "EXECUTE_SELL", "HOLD", "NO_TRADE"]
IntentDirection = Literal["BUY", "SELL", "NONE"]
EntryType = Literal["MARKET", "LIMIT", "STOP", "NONE"]

# Fields that MUST be excluded from the canonical signing payload so the
# signature is computed over a stable projection.
_SIGNED_EXCLUDE: frozenset[str] = frozenset({"authority_signature"})

# Fields explicitly forbidden from the intent payload (account-state leak).
_FORBIDDEN_FIELDS: frozenset[str] = frozenset({"balance", "equity", "margin", "free_margin", "account_balance"})


class AuthorizedOrderIntent(BaseModel):
    """Signed, immutable intent ratified by Layer-12.

    ``EXECUTE_BUY`` / ``EXECUTE_SELL`` intents MUST carry non-null entry,
    stop-loss, take-profit, lot_size, and rr_ratio. ``HOLD`` / ``NO_TRADE``
    intents carry ``direction="NONE"`` and may have null pricing fields.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=SCHEMA_VERSION)

    signal_id: str = Field(..., min_length=3)
    symbol: str = Field(..., min_length=3, max_length=20)

    verdict: Verdict
    direction: IntentDirection = Field(default="NONE")
    entry_type: EntryType = Field(default="NONE")

    entry_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    lot_size: float | None = Field(default=None, gt=0, le=100.0)
    risk_usd: float | None = Field(default=None, ge=0)
    rr_ratio: float | None = Field(default=None, gt=0)

    reason_codes: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)

    issued_at: datetime
    expires_at: datetime

    authority_signature: str = Field(
        ...,
        min_length=16,
        description="HMAC-SHA256 over canonical payload (hex)",
    )

    # ── validators ───────────────────────────────────────────────────────────

    @field_validator("reason_codes", "blockers")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for code in v:
            code = str(code).strip()
            if code and code not in seen:
                seen.add(code)
                out.append(code)
        return out

    @model_validator(mode="after")
    def _enforce_verdict_shape(self) -> AuthorizedOrderIntent:
        # Execute verdicts must be fully specified; direction must agree.
        if self.verdict in ("EXECUTE_BUY", "EXECUTE_SELL"):
            expected_dir = "BUY" if self.verdict == "EXECUTE_BUY" else "SELL"
            if self.direction != expected_dir:
                raise ValueError(f"verdict={self.verdict} requires direction={expected_dir}, got {self.direction}")
            missing = [
                name
                for name in ("entry_price", "stop_loss", "take_profit", "lot_size", "rr_ratio")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(f"verdict={self.verdict} requires non-null fields, missing: {missing}")
            if self.entry_type == "NONE":
                raise ValueError(f"verdict={self.verdict} requires entry_type != NONE")
            if not self.reason_codes:
                raise ValueError(f"verdict={self.verdict} requires at least one reason_code")
        elif self.verdict in ("HOLD", "NO_TRADE"):
            if self.direction != "NONE":
                raise ValueError(f"verdict={self.verdict} requires direction=NONE")

        # Expiry must be strictly after issuance.
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be strictly after issued_at")

        return self

    # ── signature helpers ────────────────────────────────────────────────────

    def canonical_payload(self) -> dict[str, Any]:
        """Canonical dict used for HMAC computation (excludes the signature itself)."""
        return canonical_payload(self.model_dump(mode="json"))

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(tz=UTC)
        return now >= self.expires_at

    def is_executable(self, now: datetime | None = None) -> bool:
        """True if the intent is an EXECUTE verdict and still within TTL."""
        return self.verdict in ("EXECUTE_BUY", "EXECUTE_SELL") and not self.is_expired(now=now)


# ── module-level signing/verification helpers ────────────────────────────────


def canonical_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical projection of the intent payload for signing.

    Removes the signature field itself and any forbidden (account-state) keys.
    Raises ``ValueError`` if forbidden keys are present.
    """
    leaked = _FORBIDDEN_FIELDS.intersection({k.lower() for k in payload})
    if leaked:
        raise ValueError(f"Intent payload must not carry account state; forbidden keys: {sorted(leaked)}")
    return {k: v for k, v in payload.items() if k not in _SIGNED_EXCLUDE}


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        canonical_payload(payload),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _resolve_secret(secret: str | bytes | None) -> bytes:
    if secret is None:
        secret = os.environ.get(AUTHORITY_SECRET_ENV, "")
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if not secret:
        raise RuntimeError(f"Authority secret is empty. Set {AUTHORITY_SECRET_ENV} or pass secret explicitly.")
    return secret


def compute_signature(payload: dict[str, Any], secret: str | bytes | None = None) -> str:
    """Compute HMAC-SHA256 hex digest over the canonical payload."""
    key = _resolve_secret(secret)
    body = _canonical_bytes(payload)
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def sign_intent_payload(payload: dict[str, Any], secret: str | bytes | None = None) -> AuthorizedOrderIntent:
    """Sign a raw payload dict and return a validated ``AuthorizedOrderIntent``.

    The caller supplies every field EXCEPT ``authority_signature``. This helper
    validates the payload by constructing a placeholder model first, then
    computes the HMAC over the *normalized* canonical JSON projection so that
    sign-time and verify-time operate on byte-identical canonical bytes
    regardless of input type variance (datetime repr, default fields).
    """
    if "authority_signature" in payload:
        raise ValueError("payload must not pre-populate authority_signature")
    placeholder = AuthorizedOrderIntent(**payload, authority_signature="0" * 64)
    canonical = placeholder.model_dump(mode="json")
    signature = compute_signature(canonical, secret=secret)
    return placeholder.model_copy(update={"authority_signature": signature})


def verify_intent_signature(intent: AuthorizedOrderIntent, secret: str | bytes | None = None) -> bool:
    """Constant-time verification of the intent's authority_signature."""
    expected = compute_signature(intent.model_dump(mode="json"), secret=secret)
    return hmac.compare_digest(expected, intent.authority_signature)


__all__ = [
    "SCHEMA_VERSION",
    "AUTHORITY_SECRET_ENV",
    "Verdict",
    "IntentDirection",
    "EntryType",
    "AuthorizedOrderIntent",
    "canonical_payload",
    "compute_signature",
    "sign_intent_payload",
    "verify_intent_signature",
]
