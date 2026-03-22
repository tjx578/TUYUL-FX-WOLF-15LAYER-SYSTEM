"""
Governance Gate — unified freshness / quality / kill-switch enforcement.

This module is the single authority for deciding whether the analysis pipeline
is allowed to operate normally.  It consolidates:

  A. Feed freshness guard       (per-symbol last_seen_ts)
  B. DataQualityGate            (gap ratio, low tick, staleness penalty)
  C. Producer health gate       (heartbeat presence + Redis lag)
  D. Kill-switch / no-trade guard  (hard threshold enforcement)

Returns a GovernanceVerdict that the pipeline must respect BEFORE entering
the Wolf Analysis Constitutional DAG.

Zone: state/ — governance read-only check, no execution side-effects.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from loguru import logger

from state.data_freshness import (
    FeedFreshnessSnapshot,
    classify_feed_freshness,
    stale_threshold_seconds,
)

# ---------------------------------------------------------------------------
# Governance verdict
# ---------------------------------------------------------------------------


class GovernanceAction(StrEnum):
    """What the pipeline must do after governance check."""

    ALLOW = "ALLOW"  # normal operation
    ALLOW_REDUCED = "ALLOW_REDUCED"  # degraded but allowed with penalty
    HOLD = "HOLD"  # force HOLD verdict
    BLOCK = "BLOCK"  # hard block — no analysis at all


@dataclass(frozen=True)
class GovernanceVerdict:
    """Result of the unified governance check for one symbol."""

    action: GovernanceAction
    symbol: str
    confidence_penalty: float = 0.0  # 0.0–1.0 subtracted from confidence
    reasons: tuple[str, ...] = ()
    feed_freshness: FeedFreshnessSnapshot | None = None
    producer_alive: bool = True
    warmup_ready: bool = True
    kill_switch_active: bool = False
    data_quality_degraded: bool = False

    @property
    def allow_analysis(self) -> bool:
        return self.action in (GovernanceAction.ALLOW, GovernanceAction.ALLOW_REDUCED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "symbol": self.symbol,
            "confidence_penalty": round(self.confidence_penalty, 4),
            "reasons": list(self.reasons),
            "producer_alive": self.producer_alive,
            "warmup_ready": self.warmup_ready,
            "kill_switch_active": self.kill_switch_active,
            "data_quality_degraded": self.data_quality_degraded,
            "feed_freshness": self.feed_freshness.state if self.feed_freshness else None,
        }


# ---------------------------------------------------------------------------
# Thresholds (configurable via env)
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes")


# Hard stale threshold: beyond this, force HOLD regardless
HARD_STALE_THRESHOLD_SEC = _env_float("WOLF_GOVERNANCE_HARD_STALE_SEC", 600.0)

# Heartbeat max age: producer considered dead if heartbeat older than this
HEARTBEAT_MAX_AGE_SEC = _env_float("WOLF_GOVERNANCE_HEARTBEAT_MAX_AGE_SEC", 60.0)

# WS warmup grace period: after WS reconnects, allow this many seconds
# of stale_preserved before enforcing HOLD, so HTF candles have time
# to refresh organically or via HTFRefreshScheduler.
WS_WARMUP_GRACE_SEC = _env_float("WOLF_WS_WARMUP_GRACE_SEC", 300.0)

# Data quality penalty that triggers forced HOLD
DQ_PENALTY_HOLD_THRESHOLD = _env_float("WOLF_GOVERNANCE_DQ_PENALTY_HOLD", 0.40)

# Kill-switch override
KILL_SWITCH_ENABLED_DEFAULT = _env_bool("WOLF_KILL_SWITCH_ACTIVE", False)

# Stale grace period: stale_preserved data below this age (seconds) is allowed
# with a reduced-confidence penalty instead of forcing HOLD.  Set to 0 to disable.
STALE_GRACE_SEC = _env_float("WOLF_GOVERNANCE_STALE_GRACE_SEC", 0.0)


# ---------------------------------------------------------------------------
# Governance check functions
# ---------------------------------------------------------------------------


def check_producer_health(
    heartbeat_ts: float | None,
    *,
    max_age_sec: float = HEARTBEAT_MAX_AGE_SEC,
    now_ts: float | None = None,
) -> tuple[bool, float]:
    """
    Check if the ingest producer is alive based on heartbeat timestamp.

    Returns:
        (alive: bool, age_seconds: float)
    """
    if heartbeat_ts is None or heartbeat_ts <= 0:
        return False, float("inf")
    now = now_ts if now_ts is not None else time.time()
    age = max(0.0, now - heartbeat_ts)
    return age <= max_age_sec, age


def check_kill_switch(
    redis_value: str | None = None,
) -> bool:
    """
    Check if the system kill-switch is active.

    Priority: Redis key > env var fallback.
    """
    if redis_value is not None:
        return str(redis_value).strip().lower() in ("1", "true", "yes", "active")
    return KILL_SWITCH_ENABLED_DEFAULT


def assess_governance(
    *,
    symbol: str,
    # Feed freshness
    last_seen_ts: float | None = None,
    transport_ok: bool = True,
    # Producer health
    heartbeat_ts: float | None = None,
    # Warmup
    warmup_ready: bool = True,
    # Data quality
    dq_penalty: float = 0.0,
    dq_degraded: bool = False,
    # Kill-switch
    kill_switch_value: str | None = None,
    # WS warmup grace
    ws_connected_at: float | None = None,
    # Overrides
    now_ts: float | None = None,
) -> GovernanceVerdict:
    """
    Unified governance assessment for a single symbol.

    This is the SINGLE point of truth for whether the pipeline
    may proceed with analysis for this symbol.
    """
    now = now_ts if now_ts is not None else time.time()
    reasons: list[str] = []
    total_penalty = 0.0

    # ── A. Kill-switch ───────────────────────────────────────────
    ks_active = check_kill_switch(kill_switch_value)
    if ks_active:
        return GovernanceVerdict(
            action=GovernanceAction.BLOCK,
            symbol=symbol,
            confidence_penalty=1.0,
            reasons=("kill_switch_active",),
            kill_switch_active=True,
            warmup_ready=warmup_ready,
        )

    # ── B. Warmup check ─────────────────────────────────────────
    if not warmup_ready:
        reasons.append("warmup_insufficient")

    # ── C. Feed freshness ────────────────────────────────────────
    stale_threshold_seconds()
    freshness = classify_feed_freshness(
        transport_ok=transport_ok,
        has_producer_signal=last_seen_ts is not None and last_seen_ts > 0,
        last_seen_ts=last_seen_ts,
        now_ts=now,
    )

    # Hard stale threshold — only report when staleness is finite;
    # infinite staleness is already covered by no_producer / no_transport.
    if not math.isinf(freshness.staleness_seconds) and freshness.staleness_seconds > HARD_STALE_THRESHOLD_SEC:
        reasons.append(f"hard_stale:{freshness.staleness_seconds:.0f}s>{HARD_STALE_THRESHOLD_SEC:.0f}s")

    if freshness.state == "no_producer":
        reasons.append("no_producer_signal")
    elif freshness.state == "no_transport":
        reasons.append("no_transport")
    elif freshness.state == "config_error":
        reasons.append("config_error")
    elif freshness.state == "stale_preserved":
        total_penalty += 0.15
        reasons.append(f"stale_preserved:{freshness.staleness_seconds:.0f}s")

    # ── D. Producer health ───────────────────────────────────────
    producer_alive, hb_age = check_producer_health(heartbeat_ts, max_age_sec=HEARTBEAT_MAX_AGE_SEC, now_ts=now)
    if not producer_alive:
        if math.isinf(hb_age):
            reasons.append("producer_heartbeat_dead:no_heartbeat")
        else:
            reasons.append(f"producer_heartbeat_dead:{hb_age:.0f}s")

    # ── E. Data quality ──────────────────────────────────────────
    total_penalty += max(0.0, dq_penalty)
    if dq_degraded:
        reasons.append("data_quality_degraded")

    total_penalty = min(total_penalty, 1.0)

    # ── WS Warmup grace check ────────────────────────────────────
    # After WS reconnects, HTF candles (H1/H4/D1) may still be stale
    # because they haven't completed yet. During this grace window,
    # stale_preserved is downgraded from HOLD → ALLOW_REDUCED so the
    # pipeline can resume with reduced confidence instead of blocking.
    in_ws_warmup = False
    if ws_connected_at is not None and ws_connected_at > 0:
        ws_age = now - ws_connected_at
        in_ws_warmup = 0 <= ws_age < WS_WARMUP_GRACE_SEC

    # ── Decision ─────────────────────────────────────────────────
    # BLOCK conditions (hard)
    if ks_active:
        action = GovernanceAction.BLOCK
    # HOLD conditions — check specific states first, then generic staleness
    elif freshness.state in ("no_producer", "no_transport", "config_error"):
        # P0-6: conservative — if freshness cannot be proven, HOLD.
        # Even if producer heartbeat is alive but no data arrived,
        # new-trade flow must remain blocked.
        # P0: config_error is equally untrustworthy — ambiguous freshness → HOLD.
        action = GovernanceAction.HOLD
    elif not warmup_ready or freshness.staleness_seconds > HARD_STALE_THRESHOLD_SEC:
        action = GovernanceAction.HOLD
    elif freshness.state == "stale_preserved":
        if in_ws_warmup:
            # WS just reconnected — HTF candles are stale but will refresh soon.
            # Downgrade to ALLOW_REDUCED with penalty instead of hard HOLD.
            action = GovernanceAction.ALLOW_REDUCED
            total_penalty = min(total_penalty + 0.10, 1.0)
            reasons.append(f"ws_warmup_grace:{now - ws_connected_at:.0f}s")
            logger.info(
                "Governance WS warmup grace for {}: stale_preserved but WS reconnected {:.0f}s ago — ALLOW_REDUCED",
                symbol,
                now - ws_connected_at,
            )
        elif STALE_GRACE_SEC > 0 and freshness.staleness_seconds <= STALE_GRACE_SEC:
            # Recent stale — within configurable grace window, allow with penalty.
            action = GovernanceAction.ALLOW_REDUCED
            total_penalty = min(total_penalty + 0.20, 1.0)
            reasons.append(f"stale_grace:{freshness.staleness_seconds:.0f}s<={STALE_GRACE_SEC:.0f}s")
            logger.info(
                "Governance stale grace for {}: stale_preserved {:.0f}s <= grace {:.0f}s — ALLOW_REDUCED",
                symbol,
                freshness.staleness_seconds,
                STALE_GRACE_SEC,
            )
        else:
            # P0-6: stale-preserved supports visibility/diagnosis only,
            # not silent normal-mode trading.
            action = GovernanceAction.HOLD
            if "stale_preserved" not in " ".join(reasons):
                reasons.append("stale_preserved_hold")
    elif dq_penalty >= DQ_PENALTY_HOLD_THRESHOLD:
        action = GovernanceAction.HOLD
    elif total_penalty > 0 or dq_degraded:
        action = GovernanceAction.ALLOW_REDUCED
    else:
        action = GovernanceAction.ALLOW

    verdict = GovernanceVerdict(
        action=action,
        symbol=symbol,
        confidence_penalty=total_penalty,
        reasons=tuple(reasons),
        feed_freshness=freshness,
        producer_alive=producer_alive,
        warmup_ready=warmup_ready,
        kill_switch_active=ks_active,
        data_quality_degraded=dq_degraded,
    )

    if action in (GovernanceAction.HOLD, GovernanceAction.BLOCK):
        logger.warning(
            "Governance {} for {}: {} | penalty={:.2f}",
            action.value,
            symbol,
            ", ".join(reasons),
            total_penalty,
        )

    return verdict
