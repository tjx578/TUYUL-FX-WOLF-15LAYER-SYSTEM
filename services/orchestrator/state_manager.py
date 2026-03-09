"""Runtime state manager for governance mode transitions."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from loguru import logger

from services.orchestrator.compliance_guard import evaluate_compliance
from services.orchestrator.execution_mode import ExecutionMode
from state.pubsub_channels import ORCHESTRATOR_COMMANDS
from storage.redis_client import RedisClient

ORCHESTRATOR_SOURCE = "wolf15-orchestrator"


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
        self._state_key = os.getenv("ORCHESTRATOR_STATE_KEY", "wolf15:orchestrator:state")
        self._account_state_key = os.getenv("ORCHESTRATOR_ACCOUNT_STATE_KEY", "wolf15:account:state")
        self._trade_risk_key = os.getenv("ORCHESTRATOR_TRADE_RISK_KEY", "wolf15:trade:risk")

        self._loop_sleep_sec = max(0.1, float(os.getenv("ORCHESTRATOR_LOOP_SLEEP_SEC", "0.5")))
        self._compliance_interval_sec = max(1.0, float(os.getenv("ORCHESTRATOR_COMPLIANCE_INTERVAL_SEC", "5")))
        self._heartbeat_interval_sec = max(5.0, float(os.getenv("ORCHESTRATOR_HEARTBEAT_INTERVAL_SEC", "30")))

        self._account_state: dict[str, Any] = {}
        self._trade_risk: dict[str, Any] = {}
        self._last_compliance_check = 0.0
        self._last_heartbeat = 0.0

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
        self._redis.publish(self._channel, encoded)
        self._redis.set(self._state_key, encoded)

    def _refresh_snapshots_from_redis(self) -> None:
        account_snapshot = _parse_json(self._redis.get(self._account_state_key))
        if account_snapshot:
            self._account_state.update(account_snapshot)

        risk_snapshot = _parse_json(self._redis.get(self._trade_risk_key))
        if risk_snapshot:
            self._trade_risk.update(risk_snapshot)

    def _handle_channel_message(self, payload: dict[str, Any]) -> None:
        if not payload:
            return
        if str(payload.get("source", "")).strip().lower() == ORCHESTRATOR_SOURCE:
            return

        if isinstance(payload.get("account_state"), dict):
            self._account_state.update(payload["account_state"])
        if isinstance(payload.get("trade_risk"), dict):
            self._trade_risk.update(payload["trade_risk"])

        command = str(payload.get("command") or payload.get("event") or "").upper()
        if command in {"SET_MODE", "MODE_SET"}:
            raw_mode = str(payload.get("mode", "")).upper()
            if raw_mode in ExecutionMode.__members__:
                self.set_mode(
                    ExecutionMode[raw_mode],
                    reason=str(payload.get("reason") or "command"),
                    compliance_code="EXTERNAL_COMMAND",
                )
                self.publish_state("MODE_CHANGED", {"origin": "command"})

    def _poll_channel(self) -> None:
        if self._pubsub is None:
            return

        for _ in range(64):
            message = self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.01)
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

        if self._state.mode != target_mode or self._state.compliance_code != result.code:
            self._state = OrchestratorState(
                mode=target_mode,
                reason=f"compliance:{result.code}",
                compliance_code=result.code,
                updated_at=_utc_now_iso(),
            )
            logger.warning(
                "compliance transition -> mode={} code={} severity={}",
                target_mode,
                result.code,
                result.severity,
            )
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

    def run_forever(self) -> None:
        self.start_listener()
        self.publish_state("BOOT")
        logger.info("wolf15-orchestrator started in {}", self.snapshot().mode)

        try:
            while True:
                self.process_once()
                time.sleep(self._loop_sleep_sec)
        finally:
            self.close()


def run() -> None:
    StateManager().run_forever()


if __name__ == "__main__":
    run()
