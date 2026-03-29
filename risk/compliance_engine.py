"""
Compliance Auto-Mode Engine — P1-9
====================================
Detects when account risk usage approaches prop firm limits and
transitions compliance mode accordingly:

  NORMAL → REDUCE_RISK_MODE → HARD_BLOCK

Transitions:
  - If daily or total DD usage >= 80% of limit → REDUCE_RISK_MODE.
  - If daily or total DD usage >= 95% (block threshold) → HARD_BLOCK.
  - Recovery: usage drops below 75% (hysteresis) → NORMAL.

Every mode transition emits COMPLIANCE_MODE_CHANGED to Redis Streams.

Zone: risk / compliance — veto authority, NOT market direction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from loguru import logger

from core.redis_keys import COMPLIANCE_EVENTS, compliance_state


class ComplianceMode(StrEnum):
    """Account compliance mode — controls risk posture."""

    NORMAL = "NORMAL"
    REDUCE_RISK_MODE = "REDUCE_RISK_MODE"
    HARD_BLOCK = "HARD_BLOCK"


# ── Transition rules ─────────────────────────────────────────────────────────

COMPLIANCE_TRANSITIONS: dict[ComplianceMode, frozenset[ComplianceMode]] = {
    ComplianceMode.NORMAL: frozenset({ComplianceMode.REDUCE_RISK_MODE, ComplianceMode.HARD_BLOCK}),
    ComplianceMode.REDUCE_RISK_MODE: frozenset({ComplianceMode.NORMAL, ComplianceMode.HARD_BLOCK}),
    ComplianceMode.HARD_BLOCK: frozenset({ComplianceMode.REDUCE_RISK_MODE, ComplianceMode.NORMAL}),
}


@dataclass(frozen=True)
class ComplianceModeResult:
    """Result of a compliance mode evaluation."""

    account_id: str
    previous_mode: ComplianceMode
    current_mode: ComplianceMode
    changed: bool
    reason: str
    daily_usage_percent: float
    total_usage_percent: float
    daily_threshold_warn: float
    daily_threshold_block: float
    total_threshold_warn: float
    total_threshold_block: float
    evaluated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


# ── Default thresholds ────────────────────────────────────────────────────────

DEFAULT_WARN_THRESHOLD_PERCENT = 80.0  # → REDUCE_RISK_MODE
DEFAULT_BLOCK_THRESHOLD_PERCENT = 95.0  # → HARD_BLOCK
DEFAULT_RECOVERY_THRESHOLD_PERCENT = 75.0  # ← hysteresis: drop below to recover


class ComplianceAutoModeEngine:
    """Evaluates account state against prop limits and computes compliance mode.

    Stateless per evaluation — the current mode is read from account state
    or a provided override.
    """

    def __init__(
        self,
        *,
        warn_threshold_percent: float = DEFAULT_WARN_THRESHOLD_PERCENT,
        block_threshold_percent: float = DEFAULT_BLOCK_THRESHOLD_PERCENT,
        recovery_threshold_percent: float = DEFAULT_RECOVERY_THRESHOLD_PERCENT,
        stream_publisher: Any = None,
    ) -> None:
        self._warn = warn_threshold_percent
        self._block = block_threshold_percent
        self._recovery = recovery_threshold_percent
        self._stream_publisher = stream_publisher

    def _get_publisher(self) -> Any:
        if self._stream_publisher is None:
            from infrastructure.stream_publisher import StreamPublisher  # noqa: PLC0415

            self._stream_publisher = StreamPublisher()
        return self._stream_publisher

    def evaluate(
        self,
        account_id: str,
        daily_loss_used_percent: float,
        max_daily_loss_percent: float,
        total_loss_used_percent: float,
        max_total_loss_percent: float,
        current_mode: ComplianceMode | str = ComplianceMode.NORMAL,
        *,
        daily_dd_block_threshold_percent: float | None = None,
        total_dd_block_threshold_percent: float | None = None,
    ) -> ComplianceModeResult:
        """Evaluate compliance mode based on current DD usage.

        Parameters
        ----------
        daily_dd_block_threshold_percent / total_dd_block_threshold_percent:
            Per-account overrides for block threshold (from AccountRiskState).
            Defaults to engine-level block threshold if not provided.
        """
        current = ComplianceMode(current_mode) if isinstance(current_mode, str) else current_mode

        daily_block = daily_dd_block_threshold_percent if daily_dd_block_threshold_percent is not None else self._block
        total_block = total_dd_block_threshold_percent if total_dd_block_threshold_percent is not None else self._block

        # Compute usage as percentage of limit
        daily_usage = _safe_usage_pct(daily_loss_used_percent, max_daily_loss_percent)
        total_usage = _safe_usage_pct(total_loss_used_percent, max_total_loss_percent)

        max_usage = max(daily_usage, total_usage)

        # Determine target mode
        if max_usage >= max(daily_block, total_block):
            target = ComplianceMode.HARD_BLOCK
            reason = f"DD usage {max_usage:.1f}% >= block threshold"
        elif max_usage >= self._warn:
            target = ComplianceMode.REDUCE_RISK_MODE
            reason = f"DD usage {max_usage:.1f}% >= warn threshold {self._warn}%"
        elif current != ComplianceMode.NORMAL and max_usage < self._recovery:
            target = ComplianceMode.NORMAL
            reason = f"DD usage {max_usage:.1f}% recovered below {self._recovery}% hysteresis"
        else:
            # No change — stay in current mode
            target = current
            reason = f"DD usage {max_usage:.1f}% — no transition"

        changed = target != current

        return ComplianceModeResult(
            account_id=account_id,
            previous_mode=current,
            current_mode=target,
            changed=changed,
            reason=reason,
            daily_usage_percent=daily_usage,
            total_usage_percent=total_usage,
            daily_threshold_warn=self._warn,
            daily_threshold_block=daily_block,
            total_threshold_warn=self._warn,
            total_threshold_block=total_block,
        )

    async def evaluate_and_emit(
        self,
        account_id: str,
        daily_loss_used_percent: float,
        max_daily_loss_percent: float,
        total_loss_used_percent: float,
        max_total_loss_percent: float,
        current_mode: ComplianceMode | str = ComplianceMode.NORMAL,
        *,
        daily_dd_block_threshold_percent: float | None = None,
        total_dd_block_threshold_percent: float | None = None,
    ) -> ComplianceModeResult:
        """Evaluate and emit COMPLIANCE_MODE_CHANGED event if mode changed."""
        result = self.evaluate(
            account_id=account_id,
            daily_loss_used_percent=daily_loss_used_percent,
            max_daily_loss_percent=max_daily_loss_percent,
            total_loss_used_percent=total_loss_used_percent,
            max_total_loss_percent=max_total_loss_percent,
            current_mode=current_mode,
            daily_dd_block_threshold_percent=daily_dd_block_threshold_percent,
            total_dd_block_threshold_percent=total_dd_block_threshold_percent,
        )

        if result.changed:
            await self._emit_mode_change(result)
            await self._persist_state(result)
            logger.warning(
                "[ComplianceEngine] account=%s mode %s -> %s reason=%s",
                account_id,
                result.previous_mode,
                result.current_mode,
                result.reason,
            )
        else:
            logger.debug(
                "[ComplianceEngine] account=%s mode=%s (no change) usage=%.1f%%",
                account_id,
                result.current_mode,
                max(result.daily_usage_percent, result.total_usage_percent),
            )

        return result

    def is_blocked(self, mode: ComplianceMode | str) -> bool:
        """Return True if the mode means hard-block for new execution intents."""
        return ComplianceMode(mode) == ComplianceMode.HARD_BLOCK

    def is_reduced_risk(self, mode: ComplianceMode | str) -> bool:
        """Return True if the mode means reduced risk posture."""
        return ComplianceMode(mode) == ComplianceMode.REDUCE_RISK_MODE

    async def _emit_mode_change(self, result: ComplianceModeResult) -> None:
        """Emit COMPLIANCE_MODE_CHANGED to Redis Streams."""
        try:
            publisher = self._get_publisher()
            await publisher.publish(
                stream=COMPLIANCE_EVENTS,
                fields={
                    "event_type": "COMPLIANCE_MODE_CHANGED",
                    "event_id": f"cmp_{uuid.uuid4().hex[:16]}",
                    "account_id": result.account_id,
                    "previous_mode": result.previous_mode.value,
                    "current_mode": result.current_mode.value,
                    "reason": result.reason,
                    "daily_usage_percent": str(result.daily_usage_percent),
                    "total_usage_percent": str(result.total_usage_percent),
                    "timestamp": result.evaluated_at,
                },
            )
        except Exception:
            logger.debug("[ComplianceEngine] Event emission failed", exc_info=True)

    async def _persist_state(self, result: ComplianceModeResult) -> None:
        """Cache current compliance state in Redis for fast reads."""
        try:
            import json  # noqa: PLC0415

            from storage.redis_client import redis_client  # noqa: PLC0415

            redis_client.client.set(
                compliance_state(result.account_id),
                json.dumps(
                    {
                        "account_id": result.account_id,
                        "mode": result.current_mode.value,
                        "reason": result.reason,
                        "daily_usage_percent": result.daily_usage_percent,
                        "total_usage_percent": result.total_usage_percent,
                        "updated_at": result.evaluated_at,
                    }
                ),
                ex=60 * 60,  # 1 hour TTL
            )
        except Exception:
            logger.debug("[ComplianceEngine] Redis persist failed", exc_info=True)


def _safe_usage_pct(used: float, limit: float) -> float:
    """Compute usage as percentage of limit, clamped to [0, 100]."""
    if limit <= 0:
        return 100.0 if used > 0 else 0.0
    return min(100.0, max(0.0, (used / limit) * 100.0))
