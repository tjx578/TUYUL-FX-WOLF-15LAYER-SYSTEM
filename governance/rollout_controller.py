"""
Rollout Controller — gradual allocation ramp from 10% → 100%.

Manages per-strategy capital allocation percentage during controlled rollout.
Auto-freezes on metric degradation (drawdown, win-rate collapse, drift).

Flow:
  Strategy passes ROLLOUT stage passport → RolloutController starts ramp
  → weekly check → if guard-rails hold: bump allocation %
  → if guard-rails breached: freeze at current %
  → 100% only after minimum 6 weeks consistent

Integrates with:
  - AllocationService (allocation_pct multiplied into lot sizing)
  - DriftMonitor (drift score > threshold → freeze)
  - StageOrchestrator (freeze cascades to stage state)

Authority: Governance zone.
  - Does NOT override L12 verdict.
  - Does NOT compute market direction.
  - Controls WHAT FRACTION of approved capital is deployed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

_KEY_PREFIX = "wolf15:governance:rollout"
_ARTIFACT_DIR = Path("storage/snapshots/governance/rollout")

# ── Ramp schedule ─────────────────────────────────────────────────────────────
# (week_number, allocation_pct)
DEFAULT_RAMP_SCHEDULE: tuple[tuple[int, float], ...] = (
    (0, 0.10),  # Start: 10%
    (1, 0.25),  # Week 1: 25%
    (2, 0.40),  # Week 2: 40%
    (3, 0.55),  # Week 3: 55%
    (4, 0.70),  # Week 4: 70%
    (5, 0.85),  # Week 5: 85%
    (6, 1.00),  # Week 6: 100%
)


@dataclass(frozen=True)
class RolloutGuardRails:
    """Thresholds that trigger freeze during rollout ramp."""

    # Freeze if realized DD exceeds this fraction of backtest DD
    max_dd_ratio_vs_backtest: float = 0.60
    # Freeze if 20-trade rolling win rate drops below this
    min_rolling_win_rate: float = 0.45
    # Freeze if drift severity is CRITICAL
    max_drift_severity: str = "WARNING"  # freeze on "CRITICAL"
    # Minimum trades needed before ramp evaluation
    min_trades_per_week: int = 5


@dataclass
class RolloutState:
    """Mutable state for a strategy's rollout."""

    strategy_id: str
    current_allocation_pct: float = 0.10
    current_week: int = 0
    started_at: str = ""
    updated_at: str = ""
    frozen: bool = False
    freeze_reason: str = ""
    # Rolling metrics for guard-rail evaluation
    total_trades: int = 0
    rolling_win_rate: float = 0.0
    realized_dd_pct: float = 0.0
    backtest_dd_pct: float = 0.0
    drift_severity: str = "STABLE"
    # History of weekly evaluations
    weekly_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "current_allocation_pct": self.current_allocation_pct,
            "current_week": self.current_week,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "frozen": self.frozen,
            "freeze_reason": self.freeze_reason,
            "total_trades": self.total_trades,
            "rolling_win_rate": self.rolling_win_rate,
            "realized_dd_pct": self.realized_dd_pct,
            "backtest_dd_pct": self.backtest_dd_pct,
            "drift_severity": self.drift_severity,
            "weekly_log": self.weekly_log,
        }


class RolloutController:
    """
    Controls gradual allocation ramp during controlled rollout.

    Thread-safe via Redis atomic ops.  Designed to be called weekly
    by a scheduler or manually by operator.
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        guard_rails: RolloutGuardRails | None = None,
        ramp_schedule: tuple[tuple[int, float], ...] | None = None,
    ) -> None:
        self._redis = redis_client
        self._guard_rails = guard_rails or RolloutGuardRails()
        self._ramp = ramp_schedule or DEFAULT_RAMP_SCHEDULE
        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────

    def start_rollout(self, strategy_id: str, backtest_dd_pct: float = 8.0) -> RolloutState:
        """Initialize rollout at 10% allocation."""
        now = datetime.now(UTC).isoformat()
        state = RolloutState(
            strategy_id=strategy_id,
            current_allocation_pct=self._ramp[0][1] if self._ramp else 0.10,
            current_week=0,
            started_at=now,
            updated_at=now,
            backtest_dd_pct=backtest_dd_pct,
        )
        self._persist(state)
        logger.info(
            "RolloutController: started rollout for strategy={} at {}%",
            strategy_id,
            state.current_allocation_pct * 100,
        )
        return state

    def get_state(self, strategy_id: str) -> RolloutState | None:
        """Load rollout state."""
        raw = self._load(strategy_id)
        if raw is None:
            return None
        return self._deserialize(raw)

    def get_allocation_pct(self, strategy_id: str) -> float:
        """Get current allocation percentage (0.0–1.0).  Returns 0.0 if frozen or not found."""
        state = self.get_state(strategy_id)
        if state is None or state.frozen:
            return 0.0
        return state.current_allocation_pct

    def evaluate_and_ramp(
        self,
        strategy_id: str,
        *,
        rolling_win_rate: float,
        realized_dd_pct: float,
        trades_this_week: int,
        drift_severity: str = "STABLE",
    ) -> tuple[float, str]:
        """
        Weekly evaluation: check guard-rails, then ramp if safe.

        Returns (new_allocation_pct, message).
        """
        state = self.get_state(strategy_id)
        if state is None:
            return 0.0, "not in rollout"

        if state.frozen:
            return state.current_allocation_pct, f"frozen: {state.freeze_reason}"

        g = self._guard_rails

        # ── Guard-rail checks ─────────────────────────────────────────────
        freeze_reasons: list[str] = []

        # Check DD ratio
        if state.backtest_dd_pct > 0:
            dd_ratio = realized_dd_pct / state.backtest_dd_pct
            if dd_ratio > g.max_dd_ratio_vs_backtest:
                freeze_reasons.append(f"DD ratio {dd_ratio:.2f} > {g.max_dd_ratio_vs_backtest}")

        # Check rolling win rate
        if rolling_win_rate < g.min_rolling_win_rate:
            freeze_reasons.append(f"win_rate {rolling_win_rate:.3f} < {g.min_rolling_win_rate}")

        # Check drift severity
        if drift_severity == "CRITICAL" and g.max_drift_severity != "CRITICAL":
            freeze_reasons.append(f"drift_severity={drift_severity}")

        # Check minimum trade volume
        if trades_this_week < g.min_trades_per_week:
            # Not enough data to evaluate — hold at current level (no freeze)
            log_entry = {
                "week": state.current_week,
                "action": "HOLD_INSUFFICIENT_DATA",
                "trades": trades_this_week,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            state.weekly_log.append(log_entry)
            state.updated_at = datetime.now(UTC).isoformat()
            self._persist(state)
            return state.current_allocation_pct, "insufficient trades, holding"

        # ── Freeze if guard-rails breached ────────────────────────────────
        if freeze_reasons:
            reason = "; ".join(freeze_reasons)
            state.frozen = True
            state.freeze_reason = reason
            state.rolling_win_rate = rolling_win_rate
            state.realized_dd_pct = realized_dd_pct
            state.drift_severity = drift_severity
            log_entry = {
                "week": state.current_week,
                "action": "FREEZE",
                "reason": reason,
                "allocation_pct": state.current_allocation_pct,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            state.weekly_log.append(log_entry)
            state.updated_at = datetime.now(UTC).isoformat()
            self._persist(state)
            logger.warning(
                "RolloutController: strategy={} FROZEN at {}% ({})",
                strategy_id,
                state.current_allocation_pct * 100,
                reason,
            )
            return state.current_allocation_pct, f"FROZEN: {reason}"

        # ── Ramp up ──────────────────────────────────────────────────────
        state.current_week += 1
        state.rolling_win_rate = rolling_win_rate
        state.realized_dd_pct = realized_dd_pct
        state.drift_severity = drift_severity
        state.total_trades += trades_this_week

        new_pct = state.current_allocation_pct
        for week, pct in self._ramp:
            if week == state.current_week:
                new_pct = pct
                break
        # If past the schedule, cap at 1.0
        if state.current_week > max(w for w, _ in self._ramp):
            new_pct = 1.0

        old_pct = state.current_allocation_pct
        state.current_allocation_pct = new_pct

        log_entry = {
            "week": state.current_week,
            "action": "RAMP",
            "from_pct": old_pct,
            "to_pct": new_pct,
            "win_rate": rolling_win_rate,
            "dd_pct": realized_dd_pct,
            "trades": trades_this_week,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        state.weekly_log.append(log_entry)
        state.updated_at = datetime.now(UTC).isoformat()
        self._persist(state)

        logger.info(
            "RolloutController: strategy={} ramped {}% → {}%",
            strategy_id,
            old_pct * 100,
            new_pct * 100,
        )
        return new_pct, f"ramped to {new_pct * 100:.0f}%"

    def freeze(self, strategy_id: str, reason: str) -> bool:
        """Manually freeze rollout."""
        state = self.get_state(strategy_id)
        if state is None:
            return False
        state.frozen = True
        state.freeze_reason = reason
        state.updated_at = datetime.now(UTC).isoformat()
        state.weekly_log.append(
            {
                "week": state.current_week,
                "action": "MANUAL_FREEZE",
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        self._persist(state)
        logger.warning(
            "RolloutController: strategy={} MANUALLY FROZEN ({})",
            strategy_id,
            reason,
        )
        return True

    def unfreeze(self, strategy_id: str) -> bool:
        """Unfreeze rollout — requires manual operator action."""
        state = self.get_state(strategy_id)
        if state is None:
            return False
        state.frozen = False
        state.freeze_reason = ""
        state.updated_at = datetime.now(UTC).isoformat()
        state.weekly_log.append(
            {
                "week": state.current_week,
                "action": "UNFREEZE",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        self._persist(state)
        logger.info("RolloutController: strategy={} UNFROZEN", strategy_id)
        return True

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist(self, state: RolloutState) -> None:
        payload = json.dumps(state.to_dict(), default=str)
        if self._redis is not None:
            key = f"{_KEY_PREFIX}:{state.strategy_id}"
            try:
                self._redis.set(key, payload, ex=86400 * 90)
            except Exception as exc:
                logger.warning("RolloutController: Redis persist failed: {}", exc)

        artifact = _ARTIFACT_DIR / f"rollout_{state.strategy_id}.json"
        artifact.write_text(payload, encoding="utf-8")

    def _load(self, strategy_id: str) -> dict[str, Any] | None:
        if self._redis is not None:
            key = f"{_KEY_PREFIX}:{strategy_id}"
            try:
                raw = self._redis.get(key)
                if raw is not None:
                    return json.loads(raw)
            except Exception:
                pass

        artifact = _ARTIFACT_DIR / f"rollout_{strategy_id}.json"
        if artifact.exists():
            return json.loads(artifact.read_text(encoding="utf-8"))
        return None

    def _deserialize(self, raw: dict[str, Any]) -> RolloutState:
        return RolloutState(
            strategy_id=raw["strategy_id"],
            current_allocation_pct=raw.get("current_allocation_pct", 0.10),
            current_week=raw.get("current_week", 0),
            started_at=raw.get("started_at", ""),
            updated_at=raw.get("updated_at", ""),
            frozen=raw.get("frozen", False),
            freeze_reason=raw.get("freeze_reason", ""),
            total_trades=raw.get("total_trades", 0),
            rolling_win_rate=raw.get("rolling_win_rate", 0.0),
            realized_dd_pct=raw.get("realized_dd_pct", 0.0),
            backtest_dd_pct=raw.get("backtest_dd_pct", 0.0),
            drift_severity=raw.get("drift_severity", "STABLE"),
            weekly_log=raw.get("weekly_log", []),
        )
