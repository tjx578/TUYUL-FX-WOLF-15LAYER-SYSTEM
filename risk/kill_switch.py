from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

from storage.redis_client import redis_client


_KILL_SWITCH_KEY = "RISK:KILL_SWITCH:GLOBAL"


@dataclass(frozen=True)
class KillSwitchState:
    enabled: bool
    reason: str
    updated_at: str


class GlobalKillSwitch:
    """Global execution stop switch (risk/governor authority)."""

    _instance: "GlobalKillSwitch | None" = None
    _lock = Lock()

    def __new__(cls) -> "GlobalKillSwitch":
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._state = KillSwitchState(
                        enabled=False,
                        reason="",
                        updated_at=datetime.now(UTC).isoformat(),
                    )
                    cls._instance._rw_lock = Lock()
                    cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        try:
            raw = redis_client.get(_KILL_SWITCH_KEY)
            if not raw:
                return
            payload = json.loads(raw)
            self._state = KillSwitchState(
                enabled=bool(payload.get("enabled", False)),
                reason=str(payload.get("reason", "")),
                updated_at=str(payload.get("updated_at", datetime.now(UTC).isoformat())),
            )
        except Exception:
            pass

    def _save(self) -> None:
        try:
            redis_client.set(
                _KILL_SWITCH_KEY,
                json.dumps(self.snapshot()),
            )
        except Exception:
            pass

    def enable(self, reason: str) -> dict[str, str | bool]:
        with self._rw_lock:
            self._state = KillSwitchState(
                enabled=True,
                reason=reason.strip() or "MANUAL_KILL_SWITCH",
                updated_at=datetime.now(UTC).isoformat(),
            )
            self._save()
            return self.snapshot()

    def disable(self, reason: str = "MANUAL_RELEASE") -> dict[str, str | bool]:
        with self._rw_lock:
            self._state = KillSwitchState(
                enabled=False,
                reason=reason.strip() or "MANUAL_RELEASE",
                updated_at=datetime.now(UTC).isoformat(),
            )
            self._save()
            return self.snapshot()

    def is_enabled(self) -> bool:
        return bool(self._state.enabled)

    def snapshot(self) -> dict[str, str | bool]:
        return {
            "enabled": self._state.enabled,
            "reason": self._state.reason,
            "updated_at": self._state.updated_at,
        }
