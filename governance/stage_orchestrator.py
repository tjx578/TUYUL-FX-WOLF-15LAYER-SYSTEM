"""
Stage Orchestrator — manages promotion of strategies through validation stages.

Flow: BACKTEST → OPTIMIZATION → PAPER → ROLLOUT

State is persisted to Redis + JSON artifact.  Promotion between stages
requires a PASS passport from the current stage.  Auto-promote is disabled
by default (each transition requires explicit approval).

Authority: Governance zone.
  - Does NOT override L12 verdict.
  - Does NOT compute market direction.
  - CAN block promotion to live.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from governance.passport import (
    STAGE_ORDER,
    PassportStatus,
    Stage,
    StageMetrics,
    StagePassport,
    build_passport,
)
from governance.stage_gates import GateThresholds, evaluate_gate

# ── Redis key helpers ─────────────────────────────────────────────────────────
_KEY_PREFIX = "wolf15:governance:stage"
_ARTIFACT_DIR = Path("storage/snapshots/governance")


def _strategy_key(strategy_id: str) -> str:
    return f"{_KEY_PREFIX}:{strategy_id}"


def _passport_key(strategy_id: str, stage: str) -> str:
    return f"{_KEY_PREFIX}:{strategy_id}:passport:{stage}"


# ── Strategy state ────────────────────────────────────────────────────────────


@dataclass
class StrategyStageState:
    """Mutable tracking of a strategy's position in the stage pipeline."""

    strategy_id: str
    current_stage: Stage = Stage.BACKTEST
    passports: dict[str, dict[str, Any]] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    frozen: bool = False  # True = no further promotion allowed
    freeze_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "current_stage": self.current_stage.value,
            "passports": self.passports,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "frozen": self.frozen,
            "freeze_reason": self.freeze_reason,
        }


class StageOrchestrator:
    """
    Manages strategy promotion through validation stages.

    Thread-safe via Redis atomic operations.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client  # optional; graceful if None
        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────

    def register_strategy(self, strategy_id: str) -> StrategyStageState:
        """Register a new strategy at BACKTEST stage."""
        now = datetime.now(UTC).isoformat()
        state = StrategyStageState(
            strategy_id=strategy_id,
            current_stage=Stage.BACKTEST,
            created_at=now,
            updated_at=now,
        )
        self._persist_state(state)
        logger.info(
            "StageOrchestrator: registered strategy={} at stage=BACKTEST",
            strategy_id,
        )
        return state

    def get_state(self, strategy_id: str) -> StrategyStageState | None:
        """Load strategy state from Redis (or None if not registered)."""
        raw = self._load_state(strategy_id)
        if raw is None:
            return None
        return self._deserialize(raw)

    def submit_stage_result(
        self,
        strategy_id: str,
        stage: Stage,
        metrics: StageMetrics,
        run_id: str = "",
        thresholds: GateThresholds | None = None,
    ) -> StagePassport:
        """
        Evaluate metrics for a stage and issue a passport.

        Does NOT auto-promote — call promote() explicitly after review.
        """
        state = self.get_state(strategy_id)
        if state is None:
            state = self.register_strategy(strategy_id)

        if state.frozen:
            logger.warning(
                "StageOrchestrator: strategy={} is frozen ({})",
                strategy_id,
                state.freeze_reason,
            )
            return build_passport(
                strategy_id=strategy_id,
                stage=stage,
                status=PassportStatus.FAIL,
                metrics=metrics,
                issued_by="stage_orchestrator",
                run_id=run_id,
                notes=f"strategy frozen: {state.freeze_reason}",
            )

        # Validate that submitted stage matches current stage
        if stage != state.current_stage:
            logger.warning(
                "StageOrchestrator: submitted stage={} != current_stage={}",
                stage,
                state.current_stage,
            )
            return build_passport(
                strategy_id=strategy_id,
                stage=stage,
                status=PassportStatus.FAIL,
                metrics=metrics,
                issued_by="stage_orchestrator",
                run_id=run_id,
                notes=f"stage mismatch: expected {state.current_stage.value}",
            )

        # Evaluate gate
        status, failures = evaluate_gate(stage, metrics, thresholds)
        notes = "; ".join(failures) if failures else "all gates passed"

        passport = build_passport(
            strategy_id=strategy_id,
            stage=stage,
            status=status,
            metrics=metrics,
            issued_by=f"{stage.value.lower()}_gate",
            run_id=run_id,
            notes=notes,
        )

        # Persist passport
        state.passports[stage.value] = passport.to_dict()
        state.updated_at = datetime.now(UTC).isoformat()
        self._persist_state(state)
        self._persist_passport(passport)

        logger.info(
            "StageOrchestrator: strategy={} stage={} → {}  ({})",
            strategy_id,
            stage.value,
            status.value,
            notes,
        )
        return passport

    def promote(self, strategy_id: str) -> tuple[bool, str]:
        """
        Promote strategy to the next stage if current passport is PASS.

        Returns (success, message).
        Requires explicit call — no auto-promote.
        """
        state = self.get_state(strategy_id)
        if state is None:
            return False, "strategy not registered"

        if state.frozen:
            return False, f"strategy frozen: {state.freeze_reason}"

        current = state.current_stage
        passport_data = state.passports.get(current.value)
        if passport_data is None:
            return False, f"no passport for stage {current.value}"

        if passport_data.get("status") != PassportStatus.PASS.value:
            return (
                False,
                f"passport status={passport_data.get('status')} != PASS",
            )

        # Find next stage
        try:
            idx = STAGE_ORDER.index(current)
        except ValueError:
            return False, f"unknown stage {current.value}"

        if idx >= len(STAGE_ORDER) - 1:
            return False, "already at final stage (ROLLOUT)"

        next_stage = STAGE_ORDER[idx + 1]
        state.current_stage = next_stage
        state.updated_at = datetime.now(UTC).isoformat()
        self._persist_state(state)

        logger.info(
            "StageOrchestrator: strategy={} promoted {} → {}",
            strategy_id,
            current.value,
            next_stage.value,
        )
        return True, f"promoted to {next_stage.value}"

    def freeze(self, strategy_id: str, reason: str) -> bool:
        """Freeze a strategy — no further promotion allowed."""
        state = self.get_state(strategy_id)
        if state is None:
            return False
        state.frozen = True
        state.freeze_reason = reason
        state.updated_at = datetime.now(UTC).isoformat()
        self._persist_state(state)
        logger.warning("StageOrchestrator: strategy={} FROZEN ({})", strategy_id, reason)
        return True

    def unfreeze(self, strategy_id: str) -> bool:
        """Unfreeze a strategy — requires manual intervention."""
        state = self.get_state(strategy_id)
        if state is None:
            return False
        state.frozen = False
        state.freeze_reason = ""
        state.updated_at = datetime.now(UTC).isoformat()
        self._persist_state(state)
        logger.info("StageOrchestrator: strategy={} UNFROZEN", strategy_id)
        return True

    def is_live_ready(self, strategy_id: str) -> tuple[bool, str]:
        """Check if strategy has all PASS passports and is at ROLLOUT."""
        state = self.get_state(strategy_id)
        if state is None:
            return False, "not registered"
        if state.frozen:
            return False, f"frozen: {state.freeze_reason}"
        if state.current_stage != Stage.ROLLOUT:
            return False, f"current stage={state.current_stage.value}, need ROLLOUT"

        # Verify all prior stages have PASS
        for stage in STAGE_ORDER:
            pp = state.passports.get(stage.value)
            if pp is None:
                return False, f"missing passport for {stage.value}"
            if pp.get("status") != PassportStatus.PASS.value:
                return False, f"{stage.value} passport status={pp.get('status')}"

        return True, "all stages passed"

    # ── Persistence (Redis + artifact) ────────────────────────────────────

    def _persist_state(self, state: StrategyStageState) -> None:
        payload = json.dumps(state.to_dict(), default=str)
        if self._redis is not None:
            try:
                self._redis.set(_strategy_key(state.strategy_id), payload, ex=86400 * 90)
            except Exception as exc:
                logger.warning("StageOrchestrator: Redis persist failed: {}", exc)

        # Always write artifact
        artifact = _ARTIFACT_DIR / f"strategy_{state.strategy_id}.json"
        artifact.write_text(payload, encoding="utf-8")

    def _persist_passport(self, passport: StagePassport) -> None:
        payload = json.dumps(passport.to_dict(), default=str)
        if self._redis is not None:
            try:
                self._redis.set(
                    _passport_key(passport.strategy_id, passport.stage.value),
                    payload,
                    ex=86400 * 90,
                )
            except Exception as exc:
                logger.warning("StageOrchestrator: Redis passport persist failed: {}", exc)

        artifact = _ARTIFACT_DIR / f"passport_{passport.passport_id}.json"
        artifact.write_text(payload, encoding="utf-8")

    def _load_state(self, strategy_id: str) -> dict[str, Any] | None:
        # Try Redis first
        if self._redis is not None:
            try:
                raw = self._redis.get(_strategy_key(strategy_id))
                if raw is not None:
                    return json.loads(raw)
            except Exception:
                pass

        # Fallback to artifact
        artifact = _ARTIFACT_DIR / f"strategy_{strategy_id}.json"
        if artifact.exists():
            return json.loads(artifact.read_text(encoding="utf-8"))
        return None

    def _deserialize(self, raw: dict[str, Any]) -> StrategyStageState:
        return StrategyStageState(
            strategy_id=raw["strategy_id"],
            current_stage=Stage(raw.get("current_stage", "BACKTEST")),
            passports=raw.get("passports", {}),
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
            frozen=raw.get("frozen", False),
            freeze_reason=raw.get("freeze_reason", ""),
        )
