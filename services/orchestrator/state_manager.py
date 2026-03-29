"""Runtime state manager for governance mode transitions."""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from loguru import logger

from config.logging_bootstrap import configure_loguru_logging
from core.redis_keys import (
    ACCOUNT_STATE,
    HEARTBEAT_INGEST,
    HEARTBEAT_ORCHESTRATOR,
    KILL_SWITCH,
    ORCHESTRATOR_STATE,
    TRADE_RISK,
)
from services.orchestrator.compliance_guard import evaluate_compliance
from services.orchestrator.execution_mode import ExecutionMode
from services.orchestrator.redis_commands import CommandParseError, parse_set_mode_command
from state.pubsub_channels import ORCHESTRATOR_COMMANDS
from storage.redis_client import RedisClient
from utils.market_hours import is_forex_market_open

ORCHESTRATOR_SOURCE = "wolf15-orchestrator"
_ORCHESTRATOR_READY = threading.Event()

# Redis key for manual news lock (set by API /news-lock/enable endpoint)
_NEWS_LOCK_STATE_KEY = "NEWS_LOCK:STATE"

# Ingest heartbeat staleness threshold for compliance data-freshness check.
# More generous than the per-symbol threshold (120s vs 30s) because this is
# an account-level gate, not a per-tick freshness check.
_DATA_STALE_THRESHOLD_SEC = float(os.getenv("COMPLIANCE_DATA_STALE_SEC", "120"))

configure_loguru_logging()


class OrchestratorPubSubProtocol(Protocol):
    def subscribe(self, channel: str) -> None: ...
    def close(self) -> None: ...
    def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        timeout: float = 0.0,
    ) -> dict[str, Any] | None: ...


class OrchestratorRedisProtocol(Protocol):
    def pubsub(self) -> OrchestratorPubSubProtocol: ...
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ex: int | None = None) -> None: ...
    def publish(self, channel: str, message: str) -> int: ...
    def mget(self, keys: list[str]) -> list[str | None]: ...
    def pipeline(self) -> Any: ...


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return cast(dict[str, Any], payload) if isinstance(payload, dict) else {}


def _mode_from_compliance(allowed: bool, severity: str) -> ExecutionMode:
    if allowed:
        return ExecutionMode.NORMAL
    sev = str(severity).strip().lower()
    if sev == "critical":
        return ExecutionMode.KILL_SWITCH
    return ExecutionMode.SAFE


def _verify_command_signature(payload: dict[str, Any]) -> bool:
    """Verify HMAC-SHA256 signature on a command payload.

    Returns True when ORCHESTRATOR_COMMAND_SECRET is not configured (auth
    disabled), or when the payload's ``signature`` field matches the HMAC of
    the canonical JSON of the payload (the ``signature`` key is excluded from
    the digest input).

    SEC-SVC-02: This prevents an attacker with bare Redis write access from
    forging arbitrary mode-change commands.
    """
    secret = os.getenv("ORCHESTRATOR_COMMAND_SECRET", "")
    if not secret:
        return True
    sig = str(payload.get("signature", ""))
    if not sig:
        return False
    check_payload = {k: v for k, v in payload.items() if k != "signature"}
    canonical = json.dumps(check_payload, sort_keys=True, separators=(",", ":"))
    expected = _hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return _hmac.compare_digest(expected, sig)


@dataclass(slots=True)
class OrchestratorState:
    mode: ExecutionMode = ExecutionMode.NORMAL
    reason: str = "startup"
    compliance_code: str = "INIT"
    updated_at: str = ""


class StateManager:
    def __init__(self, redis_client: OrchestratorRedisProtocol | None = None) -> None:
        super().__init__()
        self._state = OrchestratorState(updated_at=_utc_now_iso())
        self._redis: OrchestratorRedisProtocol = redis_client or RedisClient()
        self._pubsub: OrchestratorPubSubProtocol | None = None

        self._channel = os.getenv("ORCHESTRATOR_CHANNEL", ORCHESTRATOR_COMMANDS)
        self._state_key = os.getenv("ORCHESTRATOR_STATE_KEY", ORCHESTRATOR_STATE)
        self._account_state_key = os.getenv("ORCHESTRATOR_ACCOUNT_STATE_KEY", ACCOUNT_STATE)
        self._trade_risk_key = os.getenv("ORCHESTRATOR_TRADE_RISK_KEY", TRADE_RISK)

        self._loop_sleep_sec = max(0.01, float(os.getenv("ORCHESTRATOR_LOOP_SLEEP_SEC", "0.05")))
        self._compliance_interval_sec = max(1.0, float(os.getenv("ORCHESTRATOR_COMPLIANCE_INTERVAL_SEC", "5")))
        self._heartbeat_interval_sec = max(5.0, float(os.getenv("ORCHESTRATOR_HEARTBEAT_INTERVAL_SEC", "30")))

        self._account_state: dict[str, Any] = {}
        self._trade_risk: dict[str, Any] = {}
        self._last_compliance_check = 0.0
        self._last_heartbeat = 0.0
        self._recovery_count: int = 0

    def configure_intervals(self, compliance_interval_sec: float, heartbeat_interval_sec: float) -> None:
        self._compliance_interval_sec = max(1.0, float(compliance_interval_sec))
        self._heartbeat_interval_sec = max(5.0, float(heartbeat_interval_sec))

    def update_account_state(self, payload: dict[str, Any]) -> None:
        self._account_state.update(payload)

    def update_trade_risk(self, payload: dict[str, Any]) -> None:
        self._trade_risk.update(payload)

    def ingest_message(self, payload: dict[str, Any]) -> None:
        self._handle_channel_message(payload)

    def snapshot(self) -> OrchestratorState:
        return self._state

    def set_mode(self, mode: ExecutionMode, reason: str, compliance_code: str = "MANUAL") -> OrchestratorState:
        if self._state.mode == mode and self._state.reason == reason and self._state.compliance_code == compliance_code:
            return self._state
        previous_mode = self._state.mode
        self._state = OrchestratorState(
            mode=mode,
            reason=reason,
            compliance_code=compliance_code,
            updated_at=_utc_now_iso(),
        )
        logger.warning(
            "orchestrator mode changed: {} -> {} (reason={}, code={})",
            previous_mode,
            mode,
            reason,
            compliance_code,
        )
        return self._state

    def start_listener(self) -> None:
        self._pubsub = self._redis.pubsub()
        self._pubsub.subscribe(self._channel)
        logger.info("orchestrator subscribed to channel {}", self._channel)

    def close(self) -> None:
        if self._pubsub is None:
            return
        try:
            self._pubsub.close()
        finally:
            self._pubsub = None

    def _sync_kill_switch(self, mode: ExecutionMode) -> None:
        """Persist kill switch state to Redis so other services can read it."""
        try:
            if mode == ExecutionMode.KILL_SWITCH:
                self._redis.set(
                    KILL_SWITCH,
                    json.dumps(
                        {
                            "active": True,
                            "source": ORCHESTRATOR_SOURCE,
                            "reason": self._state.reason,
                            "activated_at": _utc_now_iso(),
                        }
                    ),
                )
            else:
                self._redis.set(
                    KILL_SWITCH,
                    json.dumps(
                        {
                            "active": False,
                            "source": ORCHESTRATOR_SOURCE,
                            "cleared_at": _utc_now_iso(),
                        }
                    ),
                )
        except Exception as exc:
            logger.error("Failed to sync kill switch to Redis: {}", exc)

    def publish_state(self, event: str, details: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {
            "source": ORCHESTRATOR_SOURCE,
            "event": event,
            "channel": self._channel,
            "mode": self._state.mode,
            "reason": self._state.reason,
            "compliance_code": self._state.compliance_code,
            "updated_at": self._state.updated_at,
            "timestamp": int(time.time()),
        }
        if details:
            payload["details"] = details

        encoded = json.dumps(payload)
        heartbeat_payload = json.dumps({"producer": ORCHESTRATOR_SOURCE, "ts": time.time()})
        pipe = self._redis.pipeline()
        pipe.publish(self._channel, encoded)
        pipe.set(self._state_key, encoded)
        pipe.set(HEARTBEAT_ORCHESTRATOR, heartbeat_payload)
        pipe.execute()

    def _refresh_snapshots_from_redis(self) -> None:
        raw_values = self._redis.mget([self._account_state_key, self._trade_risk_key])
        account_snapshot = _parse_json(raw_values[0])
        if account_snapshot:
            self._account_state.update(account_snapshot)

        risk_snapshot = _parse_json(raw_values[1])
        if risk_snapshot:
            self._trade_risk.update(risk_snapshot)

        self._refresh_compliance_signals()

    def _refresh_compliance_signals(self) -> None:
        """Compute and inject news_lock, session_lock, and data_stale into account state."""
        try:
            extra_keys = [_NEWS_LOCK_STATE_KEY, HEARTBEAT_INGEST]
            raw = self._redis.mget(extra_keys)
            news_raw, hb_raw = raw[0], raw[1]
        except Exception as exc:
            logger.warning("compliance signal refresh failed: {}", exc)
            return

        # ── News lock ────────────────────────────────────────────
        news_active = False
        news_reason = ""
        if news_raw:
            news_parsed = _parse_json(news_raw)
            if news_parsed:
                news_active = True
                news_reason = str(news_parsed.get("reason", "manual_lock"))
        self._account_state["news_lock_active"] = news_active
        if news_active:
            self._account_state["news_lock_reason"] = news_reason

        # ── Session lock ─────────────────────────────────────────
        market_open = is_forex_market_open()
        self._account_state["session_locked"] = not market_open
        if not market_open:
            self._account_state["session_lock_reason"] = "forex_market_closed"

        # ── Data freshness (ingest heartbeat) ────────────────────
        data_stale = False
        staleness_sec = 0.0
        freshness_class = "unknown"
        if hb_raw:
            hb_parsed = _parse_json(hb_raw)
            hb_ts = 0.0
            if hb_parsed:
                try:
                    hb_ts = float(hb_parsed.get("ts", 0))
                except (TypeError, ValueError):
                    hb_ts = 0.0
            if hb_ts > 0:
                staleness_sec = time.time() - hb_ts
                if staleness_sec > _DATA_STALE_THRESHOLD_SEC:
                    data_stale = True
                    freshness_class = "STALE_PRESERVED"
                else:
                    freshness_class = "LIVE"
            else:
                data_stale = True
                freshness_class = "NO_PRODUCER"
        else:
            data_stale = True
            freshness_class = "NO_PRODUCER"
        self._account_state["data_stale"] = data_stale
        self._account_state["staleness_seconds"] = staleness_sec
        self._account_state["feed_freshness_class"] = freshness_class

    def _handle_channel_message(self, payload: dict[str, Any]) -> None:
        if not payload:
            return
        if str(payload.get("source", "")).strip().lower() == ORCHESTRATOR_SOURCE:
            return

        # SEC-SVC-02: account_state / trade_risk are NOT accepted from pub/sub.
        # Authoritative state comes only from Redis keys via _refresh_snapshots_from_redis.
        # Accepting arbitrary dicts here would allow a Redis-access attacker to
        # spoof balance, drawdown, and compliance_mode fields.

        raw_payload = json.dumps(payload)
        try:
            set_mode_command = parse_set_mode_command(raw_payload)
        except CommandParseError as exc:
            command = str(payload.get("command") or payload.get("event") or "").strip().lower()
            if command == "set_mode":
                logger.warning("invalid set_mode command ignored: {} payload={}", exc, payload)
            return

        if set_mode_command.mode not in ExecutionMode.__members__:
            logger.warning(
                "invalid set_mode enum ignored: mode={} payload={}",
                set_mode_command.mode,
                payload,
            )
            return

        # SEC-SVC-02: Verify HMAC signature when a command secret is configured.
        if not _verify_command_signature(payload):
            logger.warning(
                "set_mode command rejected: invalid or missing HMAC signature payload={}",
                {k: v for k, v in payload.items() if k != "signature"},
            )
            return

        new_mode = ExecutionMode[set_mode_command.mode]

        # SEC-SVC-02: External commands must not downgrade an active KILL_SWITCH.
        # Only internal compliance evaluation (or a local API call) may clear it.
        if self._state.mode == ExecutionMode.KILL_SWITCH and new_mode != ExecutionMode.KILL_SWITCH:
            logger.warning(
                "set_mode command rejected: cannot downgrade KILL_SWITCH via external command "
                "requested_mode={} payload={}",
                new_mode,
                {k: v for k, v in payload.items() if k != "signature"},
            )
            return

        self.set_mode(
            new_mode,
            reason=set_mode_command.reason,
            compliance_code="EXTERNAL_COMMAND",
        )
        self._sync_kill_switch(new_mode)
        self.publish_state("MODE_CHANGED", {"origin": "command"})

    def _poll_channel(self) -> None:
        if self._pubsub is None:
            return

        for _ in range(64):
            message = self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0)
            if not message:
                break
            raw: Any = message.get("data")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            if not isinstance(raw, str):
                continue
            self._handle_channel_message(_parse_json(raw))

    def _evaluate_compliance_tick(self) -> None:
        result = evaluate_compliance(self._account_state, self._trade_risk)
        target_mode = _mode_from_compliance(result.allowed, result.severity)

        # Auto-recovery: require 3 net normal checks before resuming.
        # Decrement (not hard-reset) on non-normal to avoid oscillation deadlock
        # where rapid NORMAL/non-NORMAL flapping prevents recovery forever.
        if target_mode == ExecutionMode.NORMAL and self._state.mode != ExecutionMode.NORMAL:
            self._recovery_count += 1
            if self._recovery_count < 3:
                logger.info(
                    "compliance recovery check {}/3",
                    self._recovery_count,
                )
                return
        elif target_mode != ExecutionMode.NORMAL:
            self._recovery_count = max(0, self._recovery_count - 1)

        if self._state.mode != target_mode or self._state.compliance_code != result.code:
            self._state = OrchestratorState(
                mode=target_mode,
                reason=f"compliance:{result.code}",
                compliance_code=result.code,
                updated_at=_utc_now_iso(),
            )
            # Reset recovery counter after successful transition
            self._recovery_count = 0
            logger.warning(
                "compliance transition -> mode={} code={} severity={}",
                target_mode,
                result.code,
                result.severity,
            )
            # Persist kill switch state to Redis so other services can read it
            self._sync_kill_switch(target_mode)
            self.publish_state(
                "MODE_CHANGED",
                {
                    "compliance_allowed": result.allowed,
                    "severity": result.severity,
                    "details": result.details,
                },
            )

    def process_once(self, now: float | None = None) -> None:
        now_ts = now if now is not None else time.time()
        self._poll_channel()
        self._refresh_snapshots_from_redis()

        if now_ts - self._last_compliance_check >= self._compliance_interval_sec:
            self._last_compliance_check = now_ts
            self._evaluate_compliance_tick()

        if now_ts - self._last_heartbeat >= self._heartbeat_interval_sec:
            self._last_heartbeat = now_ts
            self.publish_state("HEARTBEAT")

    def run_forever(self, on_started: Callable[[], None] | None = None) -> None:
        self.start_listener()
        self.publish_state("BOOT")
        logger.info("wolf15-orchestrator started in {}", self.snapshot().mode)

        if on_started is not None:
            on_started()

        try:
            while True:
                self.process_once()
                time.sleep(self._loop_sleep_sec)
        finally:
            # Persist SHUTDOWN state so other services see orchestrator went down
            try:
                self.publish_state("SHUTDOWN")
                logger.info("orchestrator published SHUTDOWN state to Redis")
            except Exception as exc:
                logger.error("orchestrator failed to publish SHUTDOWN state: {}", exc)
            self.close()


def _start_health_probe_in_thread(readiness_check: Callable[[], bool] | None = None) -> None:
    """Run HealthProbe on a daemon thread so the sync event loop isn't blocked."""
    from services.shared.health_probe_launcher import start_probe_in_thread

    port = int(os.getenv("ORCHESTRATOR_HEALTH_PORT", os.getenv("PORT", "8083")))
    start_probe_in_thread(
        port=port,
        service_name="orchestrator",
        readiness_check=readiness_check,
        extra_details={
            "service_role": "orchestrator",
            "source": ORCHESTRATOR_SOURCE,
        },
    )


def run() -> None:
    _ORCHESTRATOR_READY.clear()
    _start_health_probe_in_thread(readiness_check=lambda: _ORCHESTRATOR_READY.is_set())
    try:
        StateManager().run_forever(on_started=_ORCHESTRATOR_READY.set)
    except Exception:
        logger.exception("Orchestrator fatal error — holding alive for health probe diagnostics")
        from services.shared.diagnostics import hold_alive_sync  # noqa: PLC0415

        hold_alive_sync(service_name="Orchestrator")


if __name__ == "__main__":
    run()
