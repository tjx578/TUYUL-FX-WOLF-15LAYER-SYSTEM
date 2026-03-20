"""
Risk Firewall — P1-3
=====================
Ordered risk/compliance checks that must pass before execution.

The firewall runs checks in strict order. A hard-fail on any check
short-circuits the remaining checks and blocks execution immediately.

Check order:
  1. Kill switch
  2. Prop firm limits
  3. Exposure limits
  4. Concurrent trades limit
  5. News lock
  6. Daily drawdown
  7. Pair cooldown (if enabled)
  8. Session/trading window (if enabled)

Results are persisted per take_id for audit and queryability.

Zone: risk / compliance — veto authority, NOT market direction.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from loguru import logger

from core.redis_keys import FIREWALL_EVENTS
from journal.forensic_replay import append_replay_artifact


class FirewallVerdict(StrEnum):
    """Overall firewall decision."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CheckSeverity(StrEnum):
    """Severity of a single firewall check result."""

    PASS = "PASS"
    WARN = "WARN"
    HARD_FAIL = "HARD_FAIL"
    SKIP = "SKIP"  # Check not applicable / disabled


@dataclass(frozen=True)
class FirewallCheckResult:
    """Result of a single ordered firewall check."""

    check_name: str
    order: int
    severity: CheckSeverity
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FirewallResult:
    """Immutable aggregate result of all firewall checks."""

    firewall_id: str
    take_id: str
    verdict: FirewallVerdict
    checks: tuple[FirewallCheckResult, ...]
    started_at: str
    completed_at: str
    short_circuited_at: str | None = None  # check_name where hard fail occurred

    def to_dict(self) -> dict[str, Any]:
        return {
            "firewall_id": self.firewall_id,
            "take_id": self.take_id,
            "verdict": self.verdict.value,
            "checks": [
                {
                    "check_name": c.check_name,
                    "order": c.order,
                    "severity": c.severity.value,
                    "code": c.code,
                    "message": c.message,
                    "details": c.details,
                }
                for c in self.checks
            ],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "short_circuited_at": self.short_circuited_at,
        }


class RiskFirewall:
    """Ordered risk firewall checks for take-signal execution gating.

    All checks are run in strict order. A HARD_FAIL short-circuits.
    """

    async def evaluate(
        self,
        take_id: str,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> FirewallResult:
        """Run all firewall checks in order and return immutable result."""
        firewall_id = f"fw_{uuid.uuid4().hex[:16]}"
        started_at = datetime.now(UTC).isoformat()
        checks: list[FirewallCheckResult] = []
        short_circuited_at: str | None = None

        check_functions = [
            (1, "kill_switch", self._check_kill_switch),
            (2, "prop_firm_limits", self._check_prop_firm_limits),
            (3, "exposure_limits", self._check_exposure_limits),
            (4, "concurrent_trades", self._check_concurrent_trades),
            (5, "news_lock", self._check_news_lock),
            (6, "daily_drawdown", self._check_daily_drawdown),
            (7, "pair_cooldown", self._check_pair_cooldown),
            (8, "session_window", self._check_session_window),
        ]

        for order, name, check_fn in check_functions:
            try:
                result = await check_fn(signal, account_state)
                result = FirewallCheckResult(
                    check_name=name,
                    order=order,
                    severity=result.severity,
                    code=result.code,
                    message=result.message,
                    details=result.details,
                )
            except Exception as exc:
                result = FirewallCheckResult(
                    check_name=name,
                    order=order,
                    severity=CheckSeverity.HARD_FAIL,
                    code="CHECK_ERROR",
                    message=f"Check raised exception: {exc}",
                )

            checks.append(result)

            if result.severity == CheckSeverity.HARD_FAIL:
                short_circuited_at = name
                break

        completed_at = datetime.now(UTC).isoformat()
        verdict = FirewallVerdict.REJECTED if short_circuited_at is not None else FirewallVerdict.APPROVED

        fw_result = FirewallResult(
            firewall_id=firewall_id,
            take_id=take_id,
            verdict=verdict,
            checks=tuple(checks),
            started_at=started_at,
            completed_at=completed_at,
            short_circuited_at=short_circuited_at,
        )

        # Persist result (best-effort)
        await self._persist(fw_result)
        # Emit event
        await self._emit_event(fw_result)
        try:
            append_replay_artifact(
                "firewall_result",
                correlation_id=take_id,
                payload=fw_result.to_dict(),
            )
        except Exception:
            logger.debug("[RiskFirewall] Forensic artifact append failed")

        logger.info(
            "[RiskFirewall] take_id=%s verdict=%s checks=%d short_circuit=%s",
            take_id,
            verdict.value,
            len(checks),
            short_circuited_at,
        )
        return fw_result

    # ── Individual checks ─────────────────────────────────────────────────────

    async def _check_kill_switch(
        self,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> FirewallCheckResult:
        try:
            from risk.kill_switch import GlobalKillSwitch  # noqa: PLC0415

            ks = GlobalKillSwitch()
            if ks.is_enabled():
                return FirewallCheckResult(
                    check_name="kill_switch",
                    order=1,
                    severity=CheckSeverity.HARD_FAIL,
                    code="KILL_SWITCH_ACTIVE",
                    message=f"Global kill switch active: {ks._state.reason}",
                )
        except Exception:
            pass
        return FirewallCheckResult(
            check_name="kill_switch",
            order=1,
            severity=CheckSeverity.PASS,
            code="KILL_SWITCH_OK",
            message="Kill switch not active",
        )

    async def _check_prop_firm_limits(
        self,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> FirewallCheckResult:
        try:
            from accounts.account_repository import AccountRiskState  # noqa: PLC0415
            from accounts.prop_rule_engine import PropRuleFirewall  # noqa: PLC0415

            evaluator = PropRuleFirewall()
            risk_state = (
                AccountRiskState(
                    **{k: v for k, v in account_state.items() if k in AccountRiskState.__dataclass_fields__}
                )
                if isinstance(account_state, dict)
                else account_state
            )
            result = evaluator.evaluate(
                risk_state,
                signal.get("risk_percent", 1.0),
            )
            if not result.allowed:
                return FirewallCheckResult(
                    check_name="prop_firm_limits",
                    order=2,
                    severity=CheckSeverity.HARD_FAIL,
                    code=f"PROP_FIRM_{result.reason}",
                    message=f"Prop firm limit breached: {result.reason}",
                    details={
                        "mode": result.mode,
                        "daily_buffer": result.daily_buffer_percent,
                        "total_buffer": result.total_buffer_percent,
                    },
                )
            if result.mode == "AUTO_REDUCE":
                return FirewallCheckResult(
                    check_name="prop_firm_limits",
                    order=2,
                    severity=CheckSeverity.WARN,
                    code="PROP_FIRM_AUTO_REDUCE",
                    message=f"Prop firm: risk auto-reduced to {result.allowed_risk_percent:.2f}%",
                    details={
                        "allowed_risk_percent": result.allowed_risk_percent,
                        "daily_buffer": result.daily_buffer_percent,
                        "total_buffer": result.total_buffer_percent,
                    },
                )
        except Exception as exc:
            logger.debug("[Firewall] Prop firm check skipped: %s", exc)
            return FirewallCheckResult(
                check_name="prop_firm_limits",
                order=2,
                severity=CheckSeverity.SKIP,
                code="PROP_FIRM_SKIP",
                message="Prop firm check not available",
            )
        return FirewallCheckResult(
            check_name="prop_firm_limits",
            order=2,
            severity=CheckSeverity.PASS,
            code="PROP_FIRM_OK",
            message="Prop firm limits within bounds",
        )

    async def _check_exposure_limits(
        self,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> FirewallCheckResult:
        try:
            from accounts.exposure_control import ExposureControl  # noqa: PLC0415

            ctrl = ExposureControl()
            symbol = signal.get("symbol", "")
            account_id = account_state.get("account_id", "")
            if not ctrl.is_within_limits(account_id, symbol):
                return FirewallCheckResult(
                    check_name="exposure_limits",
                    order=3,
                    severity=CheckSeverity.HARD_FAIL,
                    code="EXPOSURE_LIMIT_EXCEEDED",
                    message=f"Exposure limit exceeded for {symbol}",
                )
        except Exception:
            return FirewallCheckResult(
                check_name="exposure_limits",
                order=3,
                severity=CheckSeverity.SKIP,
                code="EXPOSURE_SKIP",
                message="Exposure check not available",
            )
        return FirewallCheckResult(
            check_name="exposure_limits",
            order=3,
            severity=CheckSeverity.PASS,
            code="EXPOSURE_OK",
            message="Exposure within limits",
        )

    async def _check_concurrent_trades(
        self,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> FirewallCheckResult:
        account_id = account_state.get("account_id", "")
        open_trades = int(account_state.get("open_positions", 0))
        max_allowed = int(account_state.get("max_concurrent_trades", 5))
        if open_trades >= max_allowed:
            return FirewallCheckResult(
                check_name="concurrent_trades",
                order=4,
                severity=CheckSeverity.HARD_FAIL,
                code="CONCURRENT_LIMIT_REACHED",
                message=f"Account {account_id} has {open_trades}/{max_allowed} open trades",
                details={"open": open_trades, "max": max_allowed},
            )
        return FirewallCheckResult(
            check_name="concurrent_trades",
            order=4,
            severity=CheckSeverity.PASS,
            code="CONCURRENT_OK",
            message=f"Concurrent trades {open_trades}/{max_allowed}",
        )

    async def _check_news_lock(
        self,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> FirewallCheckResult:
        news_locked = account_state.get("news_locked", False)
        if news_locked:
            return FirewallCheckResult(
                check_name="news_lock",
                order=5,
                severity=CheckSeverity.HARD_FAIL,
                code="NEWS_LOCK_ACTIVE",
                message="News lock is active — no new trades allowed",
            )
        return FirewallCheckResult(
            check_name="news_lock",
            order=5,
            severity=CheckSeverity.PASS,
            code="NEWS_LOCK_OK",
            message="No news lock",
        )

    async def _check_daily_drawdown(
        self,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> FirewallCheckResult:
        daily_loss = float(account_state.get("daily_loss", 0.0))
        daily_limit = float(account_state.get("daily_loss_limit", 0.0))
        if daily_limit > 0 and daily_loss >= daily_limit:
            return FirewallCheckResult(
                check_name="daily_drawdown",
                order=6,
                severity=CheckSeverity.HARD_FAIL,
                code="DAILY_DRAWDOWN_BREACHED",
                message=f"Daily loss {daily_loss:.2f} >= limit {daily_limit:.2f}",
                details={"daily_loss": daily_loss, "limit": daily_limit},
            )
        return FirewallCheckResult(
            check_name="daily_drawdown",
            order=6,
            severity=CheckSeverity.PASS,
            code="DAILY_DRAWDOWN_OK",
            message=f"Daily drawdown within limits ({daily_loss:.2f}/{daily_limit:.2f})",
        )

    async def _check_pair_cooldown(
        self,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> FirewallCheckResult:
        cooldowns = account_state.get("pair_cooldowns", {})
        symbol = signal.get("symbol", "")
        if symbol in cooldowns:
            return FirewallCheckResult(
                check_name="pair_cooldown",
                order=7,
                severity=CheckSeverity.HARD_FAIL,
                code="PAIR_COOLDOWN_ACTIVE",
                message=f"Pair {symbol} is in cooldown until {cooldowns[symbol]}",
                details={"symbol": symbol, "cooldown_until": cooldowns[symbol]},
            )
        return FirewallCheckResult(
            check_name="pair_cooldown",
            order=7,
            severity=CheckSeverity.PASS,
            code="PAIR_COOLDOWN_OK",
            message="No pair cooldown active",
        )

    async def _check_session_window(
        self,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> FirewallCheckResult:
        session_ok = account_state.get("session_allowed", True)
        if not session_ok:
            return FirewallCheckResult(
                check_name="session_window",
                order=8,
                severity=CheckSeverity.HARD_FAIL,
                code="SESSION_WINDOW_CLOSED",
                message="Trading session window is closed",
            )
        return FirewallCheckResult(
            check_name="session_window",
            order=8,
            severity=CheckSeverity.PASS,
            code="SESSION_WINDOW_OK",
            message="Trading session window open",
        )

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _persist(self, result: FirewallResult) -> None:
        """Persist firewall result to PostgreSQL (immutable)."""
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            await pg_client.execute(
                """
                INSERT INTO firewall_results (
                    firewall_id, take_id, verdict, checks,
                    started_at, completed_at, short_circuited_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (firewall_id) DO NOTHING
                """,
                result.firewall_id,
                result.take_id,
                result.verdict.value,
                json.dumps(result.to_dict()["checks"]),
                result.started_at,
                result.completed_at,
                result.short_circuited_at,
            )
        except Exception:
            logger.warning("[RiskFirewall] PG persist failed", exc_info=True)

        # Also cache in Redis
        try:
            from storage.redis_client import redis_client  # noqa: PLC0415

            redis_client.client.set(
                f"firewall:{result.firewall_id}",
                json.dumps(result.to_dict()),
                ex=60 * 60 * 24 * 7,
            )
        except Exception:
            pass

    async def _emit_event(self, result: FirewallResult) -> None:
        """Emit firewall result event."""
        event_type = "FIREWALL_APPROVED" if result.verdict == FirewallVerdict.APPROVED else "FIREWALL_REJECTED"
        try:
            from infrastructure.stream_publisher import StreamPublisher  # noqa: PLC0415

            publisher = StreamPublisher()
            await publisher.publish(
                stream=FIREWALL_EVENTS,
                fields={
                    "event_type": event_type,
                    "firewall_id": result.firewall_id,
                    "take_id": result.take_id,
                    "verdict": result.verdict.value,
                    "short_circuited_at": result.short_circuited_at or "",
                    "timestamp": result.completed_at,
                },
            )
        except Exception:
            logger.debug("[RiskFirewall] Event emission failed")

    @staticmethod
    async def ensure_table() -> None:
        """Create the firewall_results table if it does not exist."""
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            await pg_client.execute(
                """
                CREATE TABLE IF NOT EXISTS firewall_results (
                    firewall_id         TEXT PRIMARY KEY,
                    take_id             TEXT NOT NULL,
                    verdict             TEXT NOT NULL,
                    checks              JSONB NOT NULL,
                    started_at          TEXT NOT NULL,
                    completed_at        TEXT NOT NULL,
                    short_circuited_at  TEXT
                )
                """
            )
            await pg_client.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_firewall_take_id
                ON firewall_results (take_id)
                """
            )
        except Exception:
            logger.warning("[RiskFirewall] Table creation failed", exc_info=True)
