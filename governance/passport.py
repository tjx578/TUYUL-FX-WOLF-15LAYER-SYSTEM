"""
Stage Passport — immutable proof that a strategy passed a validation stage.

Each passport is a frozen record stamped by one of:
  BACKTEST → OPTIMIZATION → PAPER → ROLLOUT

A strategy cannot advance to the next stage without a PASS passport
from the current stage.  Passports are persisted to Redis + JSON artifact
for full audit trail.

Authority: Governance zone only.  Does NOT override L12 verdict.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Stage(StrEnum):
    """Ordered validation stages."""

    BACKTEST = "BACKTEST"
    OPTIMIZATION = "OPTIMIZATION"
    PAPER = "PAPER"
    ROLLOUT = "ROLLOUT"


# Canonical promotion order
STAGE_ORDER: tuple[Stage, ...] = (
    Stage.BACKTEST,
    Stage.OPTIMIZATION,
    Stage.PAPER,
    Stage.ROLLOUT,
)


class PassportStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    CONDITIONAL = "CONDITIONAL"
    PENDING = "PENDING"


@dataclass(frozen=True)
class StageMetrics:
    """Metrics attached to a stage passport."""

    sharpe: float = 0.0
    max_drawdown_pct: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    sample_trades: int = 0
    oos_degradation_pct: float = 0.0
    stability_score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StagePassport:
    """Immutable proof that a strategy passed (or failed) a validation stage."""

    passport_id: str
    strategy_id: str
    stage: Stage
    status: PassportStatus
    metrics: StageMetrics
    issued_at: str  # ISO 8601
    issued_by: str  # e.g. "backtest_gate", "paper_gate"
    run_id: str = ""
    notes: str = ""
    checksum: str = ""  # sha256 of canonical payload

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stage"] = self.stage.value
        d["status"] = self.status.value
        return d

    @staticmethod
    def compute_checksum(
        strategy_id: str,
        stage: str,
        status: str,
        metrics_dict: dict[str, Any],
        run_id: str,
    ) -> str:
        """Deterministic SHA-256 of canonical passport payload."""
        canonical = json.dumps(
            {
                "strategy_id": strategy_id,
                "stage": stage,
                "status": status,
                "metrics": metrics_dict,
                "run_id": run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


def build_passport(
    *,
    strategy_id: str,
    stage: Stage,
    status: PassportStatus,
    metrics: StageMetrics,
    issued_by: str,
    run_id: str = "",
    notes: str = "",
) -> StagePassport:
    """Factory: create a passport with auto-generated id & checksum."""
    now = datetime.now(UTC).isoformat()
    metrics_dict = metrics.to_dict()
    checksum = StagePassport.compute_checksum(strategy_id, stage.value, status.value, metrics_dict, run_id)
    passport_id = f"pp_{strategy_id}_{stage.value}_{checksum[:12]}"
    return StagePassport(
        passport_id=passport_id,
        strategy_id=strategy_id,
        stage=stage,
        status=status,
        metrics=metrics,
        issued_at=now,
        issued_by=issued_by,
        run_id=run_id,
        notes=notes,
        checksum=checksum,
    )
