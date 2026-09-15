"""Shared interpretation of a cached L12 verdict record.

Several read surfaces interpret the same stored verdict: the L12 routes, the
internal verdict-path diagnostic, and the read-only dashboard pair-state
projection.  They have to agree on what a record *means* -- which governance
action it implies, why it is held or blocked, and when it counts as stale --
so that normalization lives here instead of being reimplemented per caller.

Read-only by construction: nothing here mutates state, issues a verdict, or
carries execution authority.
"""

from __future__ import annotations

import math
import time
from typing import Any

from state.governance_gate import GovernanceAction

# Verdicts older than this are reported STALE.  The verdict cache TTL is much
# longer (see storage.l12_cache), so a cached record can be well-formed and
# stale at the same time.
VERDICT_STALE_THRESHOLD_SECONDS = 300.0

_REASON_PREFIXES: tuple[str, ...] = (
    "GOVERNANCE_BLOCK:",
    "GOVERNANCE_HOLD:",
    "WARMUP_INSUFFICIENT:",
)

# The token before the first ":" in a hold/block reason.  The text after it is
# free-form governance detail and is never part of a viewer-safe projection.
REASON_CODES: frozenset[str] = frozenset(
    {"HOLD", "BLOCK", "GOVERNANCE_HOLD", "GOVERNANCE_BLOCK", "WARMUP_INSUFFICIENT"}
)

_ADMISSION_ACTIONS: frozenset[str] = frozenset(action.value for action in GovernanceAction)


# The verdict values Layer 12 actually persists.  tests/contract/test_api_contracts.py
# declares six for /api/v1/verdict/all; constitution/verdict_engine.py also emits the
# two reduced-risk variants on a near pass or a governance downgrade.
VERDICT_STATES: frozenset[str] = frozenset(
    {
        "EXECUTE",
        "EXECUTE_BUY",
        "EXECUTE_SELL",
        "EXECUTE_REDUCED_RISK_BUY",
        "EXECUTE_REDUCED_RISK_SELL",
        "NO_TRADE",
        "HOLD",
        "ABORT",
    }
)


def verdict_state(raw: dict[str, Any] | None) -> str | None:
    """The stored verdict, constrained to the declared set."""
    if not raw:
        return None
    verdict = raw.get("verdict")
    return verdict if isinstance(verdict, str) and verdict in VERDICT_STATES else None


def snapshot_age_seconds(raw: dict[str, Any] | None, now: float | None = None) -> float | None:
    """Age of a cached verdict, preferring the server-stamped cache time.

    Mirrors the internal verdict-path diagnostic: ``_cached_at`` is authoritative,
    ``timestamp`` is the fallback, and an unreadable value stays unmeasured.
    """
    if not raw:
        return None
    stamped = raw.get("_cached_at")
    if stamped is None:
        stamped = raw.get("timestamp")
    value: float | None = None
    if isinstance(stamped, int | float) and not isinstance(stamped, bool):
        value = float(stamped)
    elif isinstance(stamped, str) and stamped.strip():
        try:
            value = float(stamped)
        except ValueError:
            return None
    if value is None or not math.isfinite(value):
        return None
    age = (time.time() if now is None else now) - value
    # A snapshot stamped in the future has unverifiable freshness -- the clocks
    # disagree -- so it is unmeasured rather than a positive live signal.
    if not math.isfinite(age) or age < 0:
        return None
    return age


def extract_hold_block_reason(raw: dict[str, Any] | None) -> str | None:
    """Return the recorded hold/block reason for a verdict, if it carries one."""
    if not raw:
        return None
    reason = raw.get("last_hold_block_reason")
    if isinstance(reason, str) and reason:
        return reason
    errors = raw.get("errors")
    if isinstance(errors, list):
        for err in errors:
            if isinstance(err, str) and err.startswith(_REASON_PREFIXES):
                return err
    return None


def extract_governance_action(raw: dict[str, Any] | None) -> str:
    """Normalize a verdict record to the governance action it implies.

    An absent record is ``UNKNOWN``; a record with no explicit action but a
    hold/block reason is derived from that reason; anything else is ``ALLOW``.
    """
    if not raw:
        return "UNKNOWN"
    governance = raw.get("governance")
    if isinstance(governance, dict):
        action = governance.get("action")
        if isinstance(action, str) and action:
            return action
    reason = extract_hold_block_reason(raw)
    if reason:
        if reason.startswith("GOVERNANCE_BLOCK"):
            return "BLOCK"
        if reason.startswith("GOVERNANCE_HOLD") or reason.startswith("WARMUP_INSUFFICIENT"):
            return "HOLD"
    return "ALLOW"


def admission_state(raw: dict[str, Any] | None) -> str | None:
    """Governance action, but only where the record affirmatively carries one.

    ``extract_governance_action`` defaults to ``ALLOW`` for a record that simply
    has no governance block.  That default is right for the internal diagnostic
    that has always used it, but wrong to publish: a degraded HOLD written after
    a pipeline timeout or error carries neither an action nor a recognized
    governance reason, and reporting it as a positive admission would claim
    governance ran when it did not.

    So this reads the record directly instead of reusing that default:

      * an explicit, declared ``governance.action`` is published;
      * otherwise a recognized governance reason yields BLOCK or HOLD;
      * anything else is None -- unmeasured, never assumed.
    """
    if not raw:
        return None
    governance = raw.get("governance")
    if isinstance(governance, dict):
        action = governance.get("action")
        if isinstance(action, str) and action in _ADMISSION_ACTIONS:
            return action
    reason = extract_hold_block_reason(raw)
    if reason:
        if reason.startswith("GOVERNANCE_BLOCK"):
            return GovernanceAction.BLOCK.value
        if reason.startswith(("GOVERNANCE_HOLD", "WARMUP_INSUFFICIENT")):
            return GovernanceAction.HOLD.value
    return None


def reason_code(raw: dict[str, Any] | None) -> str | None:
    """Viewer-safe form of the hold/block reason: the leading token only."""
    reason = extract_hold_block_reason(raw)
    if not reason:
        return None
    token = reason.split(":", 1)[0].strip()
    return token if token in REASON_CODES else None


def quality_state(age_seconds: float | None) -> str | None:
    """Derive freshness from snapshot age.  Unknown age stays unmeasured."""
    if age_seconds is None:
        return None
    return "LIVE" if age_seconds <= VERDICT_STALE_THRESHOLD_SECONDS else "STALE"


def warmup_state(raw: dict[str, Any] | None) -> bool | None:
    """Only publish the engine's measured readiness in this cached cycle."""
    ready = raw.get("warmup_ready") if raw else None
    return ready if isinstance(ready, bool) else None
