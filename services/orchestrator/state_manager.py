"""Runtime state manager for governance mode transitions.

Guard mappings (Redis key → compliance input):
  ACCOUNT_STATE      → balance, equity, drawdown  → account health gates
  TRADE_RISK         → risk/exposure limits        → risk limit gates
  NEWS_LOCK:STATE    → news_lock_active            → news event lockout
  HEARTBEAT_INGEST   → data_stale, staleness_sec   → data freshness gate
  (runtime)          → session_locked              → forex market hours gate

See contracts/README.md for coverage status.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import redis.client
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
from services.orchestrator.ownership import OwnershipLostError, RedisFencedOwnership
from services.orchestrator.redis_commands import CommandParseError, parse_set_mode_command
from state.pubsub_channels import ORCHESTRATOR_COMMANDS
from storage.redis_client import RedisClient
from utils.market_hours import is_forex_market_open

ORCHESTRATOR_SOURCE = "wolf15-orchestrator"
_ORCHESTRATOR_READY = threading.Event()
_STATE_SCHEMA = "wolf15.orchestrator.state/v2"
_COMMITTED_STATE_MARKER = "COMMITTED"

# Redis key for manual news lock (set by API /news-lock/enable endpoint)
_NEWS_LOCK_STATE_KEY = "NEWS_LOCK:STATE"

# Ingest heartbeat staleness threshold for compliance data-freshness check.
# More generous than the per-symbol threshold (120s vs 30s) because this is
# an account-level gate, not a per-tick freshness check.
_DATA_STALE_THRESHOLD_SEC = float(os.getenv("COMPLIANCE_DATA_STALE_SEC", "120"))

configure_loguru_logging()


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


class StateHydrationError(RuntimeError):
    """Raised when persisted orchestrator state is unsafe to resume."""


class RuntimeSupervisor:
    """Thread-safe runtime truth consumed by liveness/readiness probes."""

    def __init__(self, *, stall_timeout_sec: float) -> None:
        if stall_timeout_sec <= 0:
            raise ValueError("stall timeout must be positive")
        self._stall_timeout_sec = stall_timeout_sec
        self._lock = threading.Lock()
        self._state = "STARTING"
        self._last_progress = time.monotonic()
        self._fatal_reason = ""

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def mark_standby(self) -> None:
        self._set_state("STANDBY")

    def mark_owner(self) -> None:
        self._set_state("OWNER")

    def mark_progress(self) -> None:
        with self._lock:
            self._last_progress = time.monotonic()

    def mark_fatal(self, exc: BaseException) -> None:
        with self._lock:
            self._state = "FATAL"
            self._fatal_reason = type(exc).__name__

    def mark_stopped(self) -> None:
        self._set_state("STOPPED")

    def is_alive(self) -> bool:
        with self._lock:
            if self._state in {"FATAL", "STOPPED"}:
                return False
            return (time.monotonic() - self._last_progress) <= self._stall_timeout_sec

    def is_ready(self) -> bool:
        with self._lock:
            if self._state != "OWNER":
                return False
            return (time.monotonic() - self._last_progress) <= self._stall_timeout_sec

    def details(self) -> dict[str, str]:
        with self._lock:
            return {"runtime_state": self._state, "fatal_error": self._fatal_reason}

    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state = state
            self._last_progress = time.monotonic()


class StateManager:
    def __init__(
        self,
        redis_client: RedisClient | None = None,
        *,
        ownership: RedisFencedOwnership | None = None,
        supervisor: RuntimeSupervisor | None = None,
    ) -> None:
        super().__init__()
        self._state = OrchestratorState(updated_at=_utc_now_iso())
        self._redis: RedisClient = redis_client or RedisClient()
        self._pubsub: redis.client.PubSub | None = None

        self._channel = os.getenv("ORCHESTRATOR_CHANNEL", ORCHESTRATOR_COMMANDS)
        self._state_key = os.getenv("ORCHESTRATOR_STATE_KEY", ORCHESTRATOR_STATE)
        self._account_state_key = os.getenv("ORCHESTRATOR_ACCOUNT_STATE_KEY", ACCOUNT_STATE)
        self._trade_risk_key = os.getenv("ORCHESTRATOR_TRADE_RISK_KEY", TRADE_RISK)

        self._loop_sleep_sec = max(0.01, float(os.getenv("ORCHESTRATOR_LOOP_SLEEP_SEC", "0.05")))
        self._compliance_interval_sec = max(1.0, float(os.getenv("ORCHESTRATOR_COMPLIANCE_INTERVAL_SEC", "5")))
        self._heartbeat_interval_sec = max(5.0, float(os.getenv("ORCHESTRATOR_HEARTBEAT_INTERVAL_SEC", "30")))

        lease_ttl_sec = float(os.getenv("ORCHESTRATOR_LEASE_TTL_SEC", "15"))
        self._lease_renew_interval_sec = float(
            os.getenv("ORCHESTRATOR_LEASE_RENEW_INTERVAL_SEC", str(lease_ttl_sec / 3))
        )
        if self._lease_renew_interval_sec <= 0 or self._lease_renew_interval_sec >= lease_ttl_sec / 2:
            raise ValueError("lease renewal interval must be positive and less than half the lease ttl")
        owner_prefix = (
            os.getenv("ORCHESTRATOR_OWNER_ID")
            or ":".join(
                filter(
                    None,
                    (
                        os.getenv("RAILWAY_DEPLOYMENT_ID"),
                        os.getenv("RAILWAY_REPLICA_ID"),
                    ),
                )
            )
            or "local"
        )
        # Always append a process nonce. Even a mistakenly shared configured
        # owner label must never let two processes renew each other's lease.
        owner_id = f"{owner_prefix}:{uuid.uuid4().hex}"
        self._ownership = ownership or RedisFencedOwnership(
            self._redis,
            owner_id=owner_id,
            lease_key=os.getenv("ORCHESTRATOR_LEASE_KEY", "wolf15:orchestrator:owner"),
            generation_key=os.getenv("ORCHESTRATOR_FENCE_COUNTER_KEY", "wolf15:orchestrator:fence_generation"),
            ttl_seconds=lease_ttl_sec,
        )
        stall_timeout_sec = float(
            os.getenv(
                "ORCHESTRATOR_STALL_TIMEOUT_SEC",
                str(max(30.0, self._compliance_interval_sec * 3)),
            )
        )
        self._supervisor = supervisor or RuntimeSupervisor(stall_timeout_sec=stall_timeout_sec)

        self._account_state: dict[str, Any] = {}
        self._trade_risk: dict[str, Any] = {}
        self._last_compliance_check = 0.0
        self._last_heartbeat = 0.0
        self._state_revision: int = 0
        self._legacy_import: dict[str, Any] | None = None
        # Recovery progress intentionally remains process-local.  It is a
        # debounce counter, not compliance authority; carrying partial
        # progress across a restart could clear SAFE/KILL_SWITCH too early.
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
        pubsub = self._redis.pubsub()
        pubsub.subscribe(self._channel)
        self._pubsub = pubsub
        logger.info("orchestrator subscribed to channel {}", self._channel)

    def close(self) -> None:
        pubsub = self._pubsub
        if pubsub is None:
            return
        try:
            pubsub.close()
        finally:
            self._pubsub = None

    def _sync_kill_switch(self, mode: ExecutionMode) -> None:
        """Persist kill switch state to Redis so other services can read it."""
        try:
            if mode == ExecutionMode.KILL_SWITCH:
                self._ownership.fenced_value_write(
                    key=KILL_SWITCH,
                    value=json.dumps(
                        {
                            "active": True,
                            "source": ORCHESTRATOR_SOURCE,
                            "reason": self._state.reason,
                            "activated_at": _utc_now_iso(),
                        }
                    ),
                )
            else:
                self._ownership.fenced_value_write(
                    key=KILL_SWITCH,
                    value=json.dumps(
                        {
                            "active": False,
                            "source": ORCHESTRATOR_SOURCE,
                            "cleared_at": _utc_now_iso(),
                        }
                    ),
                )
        except OwnershipLostError:
            raise
        except Exception as exc:
            logger.error("Failed to sync kill switch to Redis: {}", exc)
            raise

    def publish_state(self, event: str, details: dict[str, Any] | None = None) -> None:
        from services.orchestrator.legacy_import_contract import validate_provenance

        identity = self._ownership.identity
        if identity is None:
            raise OwnershipLostError("state publication requires an active ownership lease")
        next_revision = self._state_revision + 1
        payload: dict[str, Any] = {
            "schema": _STATE_SCHEMA,
            "commit_marker": _COMMITTED_STATE_MARKER,
            "state_revision": next_revision,
            "source": ORCHESTRATOR_SOURCE,
            "event": event,
            "channel": self._channel,
            "mode": self._state.mode,
            "reason": self._state.reason,
            "compliance_code": self._state.compliance_code,
            "updated_at": self._state.updated_at,
            "timestamp": int(time.time()),
            "owner_id": identity.owner_id,
            "fence_generation": identity.generation,
        }
        if details:
            payload["details"] = details
        if self._legacy_import is not None:
            payload["legacy_import"] = validate_provenance(
                self._legacy_import, owner=identity.owner_id, generation=identity.generation
            )

        encoded = json.dumps(payload)
        heartbeat_payload = json.dumps(
            {
                "producer": ORCHESTRATOR_SOURCE,
                "ts": time.time(),
                "owner_id": identity.owner_id,
                "fence_generation": identity.generation,
            }
        )
        self._ownership.fenced_state_write(
            state_key=self._state_key,
            state_payload=encoded,
            heartbeat_key=HEARTBEAT_ORCHESTRATOR,
            heartbeat_payload=heartbeat_payload,
            channel=self._channel,
        )
        # The fenced Redis operation is the commit boundary.  Never advance
        # the in-process watermark before Redis confirms the atomic write.
        self._state_revision = next_revision

    def hydrate_committed_state(self) -> bool:
        """Restore the last atomically committed state before publishing BOOT.

        A prior state is eligible only when it is a v2 committed envelope
        produced by this orchestrator and its fence generation predates the
        lease currently held by this process.  Missing state is a valid first
        start; malformed, uncommitted, or mismatched state fails closed.
        """
        from services.orchestrator.legacy_import_contract import ImportHoldError, strict_json, validate_provenance

        identity = self._ownership.identity
        if identity is None:
            raise OwnershipLostError("state hydration requires an active ownership lease")

        raw = self._redis.get(self._state_key)
        if raw is None:
            self._state_revision = 0
            self._recovery_count = 0
            self._legacy_import = None
            return False
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="strict")
        if not isinstance(raw, str):
            raise StateHydrationError("persisted orchestrator state is not text")

        try:
            payload = strict_json(raw)
        except (TypeError, ValueError) as exc:
            raise StateHydrationError("persisted orchestrator state is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise StateHydrationError("persisted orchestrator state is not an object")
        if payload.get("schema") != _STATE_SCHEMA:
            raise StateHydrationError("persisted orchestrator state schema mismatch")
        if payload.get("commit_marker") != _COMMITTED_STATE_MARKER:
            raise StateHydrationError("persisted orchestrator state is not committed")
        if payload.get("source") != ORCHESTRATOR_SOURCE or payload.get("channel") != self._channel:
            raise StateHydrationError("persisted orchestrator state authority mismatch")

        prior_generation = payload.get("fence_generation")
        prior_revision = payload.get("state_revision")
        if (
            not isinstance(prior_generation, int)
            or isinstance(prior_generation, bool)
            or not isinstance(prior_revision, int)
            or isinstance(prior_revision, bool)
        ):
            raise StateHydrationError("persisted orchestrator state watermark is invalid")
        prior_owner_id = payload.get("owner_id")
        if not isinstance(prior_owner_id, str) or not prior_owner_id or prior_owner_id == identity.owner_id:
            raise StateHydrationError("persisted orchestrator owner identity is stale or mismatched")
        if prior_generation < 1 or prior_generation >= identity.generation:
            raise StateHydrationError("persisted orchestrator state fence generation is stale or mismatched")
        if prior_revision < 1:
            raise StateHydrationError("persisted orchestrator state revision is invalid")

        try:
            mode = ExecutionMode(str(payload["mode"]))
        except (KeyError, ValueError) as exc:
            raise StateHydrationError("persisted orchestrator mode is invalid") from exc
        reason = payload.get("reason")
        compliance_code = payload.get("compliance_code")
        updated_at = payload.get("updated_at")
        if not isinstance(reason, str) or not reason:
            raise StateHydrationError("persisted orchestrator state fields are incomplete")
        if not isinstance(compliance_code, str) or not compliance_code:
            raise StateHydrationError("persisted orchestrator state fields are incomplete")
        if not isinstance(updated_at, str) or not updated_at:
            raise StateHydrationError("persisted orchestrator state fields are incomplete")
        try:
            datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise StateHydrationError("persisted orchestrator updated_at is invalid") from exc

        provenance = None
        if "legacy_import" in payload:
            try:
                provenance = validate_provenance(
                    payload["legacy_import"], owner=prior_owner_id, generation=prior_generation
                )
            except ImportHoldError as exc:
                raise StateHydrationError("persisted legacy import provenance is invalid") from exc

        self._state = OrchestratorState(
            mode=mode,
            reason=reason,
            compliance_code=compliance_code,
            updated_at=updated_at,
        )
        self._state_revision = prior_revision
        self._recovery_count = 0
        self._legacy_import = provenance
        return True

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
        """Compute and inject news_lock, session_lock, and data_stale into account state.

        Guard mapping (see contracts/README.md § Orchestrator guard mappings):
          NEWS_LOCK:STATE   → news_lock_active / news_lock_reason
          HEARTBEAT_INGEST  → data_stale / staleness_seconds / feed_freshness_class
          is_forex_market_open() → session_locked / session_lock_reason
        """
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
        pubsub = self._pubsub
        if pubsub is None:
            return

        for _ in range(64):
            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0)
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
        if not self._ownership.held:
            raise OwnershipLostError("compliance evaluation requires an active ownership lease")
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
        last_renewal = 0.0
        started_callback_sent = False
        hydration_completed = False
        try:
            while True:
                if not self._ownership.held:
                    hydration_completed = False
                    self._supervisor.mark_standby()
                    if not self._ownership.acquire():
                        time.sleep(self._loop_sleep_sec)
                        continue
                    hydrated = self.hydrate_committed_state()
                    hydration_completed = True
                    self.start_listener()
                    self._supervisor.mark_owner()
                    self.publish_state(
                        "BOOT",
                        {
                            "hydrated": hydrated,
                            "prior_state_revision": self._state_revision,
                        },
                    )
                    logger.info(
                        "wolf15-orchestrator acquired ownership generation={} mode={}",
                        self._ownership.identity.generation if self._ownership.identity else "unknown",
                        self.snapshot().mode,
                    )
                    last_renewal = time.monotonic()
                    if on_started is not None and not started_callback_sent:
                        on_started()
                        started_callback_sent = True

                if time.monotonic() - last_renewal >= self._lease_renew_interval_sec:
                    if not self._ownership.renew():
                        logger.warning("orchestrator ownership renewal rejected; entering standby")
                        self.close()
                        self._supervisor.mark_standby()
                        continue
                    last_renewal = time.monotonic()

                try:
                    self.process_once()
                except OwnershipLostError:
                    logger.warning("orchestrator fenced write rejected; entering standby")
                    self.close()
                    self._supervisor.mark_standby()
                    continue
                self._supervisor.mark_progress()
                time.sleep(self._loop_sleep_sec)
        except Exception as exc:
            self._supervisor.mark_fatal(exc)
            raise
        finally:
            if self._ownership.held:
                # A rejected hydration must preserve the stored bytes, including
                # after reacquisition; uninitialized state cannot settle them.
                if hydration_completed:
                    try:
                        self.publish_state("SHUTDOWN")
                        logger.info("orchestrator published SHUTDOWN state to Redis")
                    except Exception as exc:
                        logger.error("orchestrator failed to publish fenced SHUTDOWN state: {}", exc)
                try:
                    self._ownership.release()
                except Exception as exc:
                    logger.error("orchestrator ownership release failed: {}", exc)
            self.close()
            if self._supervisor.state != "FATAL":
                self._supervisor.mark_stopped()


def _start_health_probe_in_thread(
    readiness_check: Callable[[], bool] | None = None,
    liveness_check: Callable[[], bool] | None = None,
    details_provider: Callable[[], dict[str, str]] | None = None,
) -> None:
    """Run HealthProbe on a daemon thread so the sync event loop isn't blocked."""
    from services.shared.health_probe_launcher import start_probe_in_thread

    port = int(os.getenv("ORCHESTRATOR_HEALTH_PORT", os.getenv("PORT", "8083")))
    start_probe_in_thread(
        port=port,
        service_name="orchestrator",
        readiness_check=readiness_check,
        liveness_check=liveness_check,
        details_provider=details_provider,
        extra_details={
            "service_role": "orchestrator",
            "source": ORCHESTRATOR_SOURCE,
        },
    )


def run() -> None:
    _ORCHESTRATOR_READY.clear()
    compliance_interval = max(1.0, float(os.getenv("ORCHESTRATOR_COMPLIANCE_INTERVAL_SEC", "5")))
    stall_timeout = float(os.getenv("ORCHESTRATOR_STALL_TIMEOUT_SEC", str(max(30.0, compliance_interval * 3))))
    supervisor = RuntimeSupervisor(stall_timeout_sec=stall_timeout)
    _start_health_probe_in_thread(
        readiness_check=supervisor.is_ready,
        liveness_check=supervisor.is_alive,
        details_provider=supervisor.details,
    )
    try:
        StateManager(supervisor=supervisor).run_forever(on_started=_ORCHESTRATOR_READY.set)
    except Exception:
        logger.exception("Orchestrator fatal error — exiting for bounded platform restart")
        raise


if __name__ == "__main__":
    run()
