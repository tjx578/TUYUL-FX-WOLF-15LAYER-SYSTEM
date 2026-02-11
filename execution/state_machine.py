"""
Execution State Machine
Manages execution lifecycle states.
"""

from threading import Lock

from utils.timezone_utils import now_utc


class ExecutionStateMachine:
    _instance = None
    _lock = Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self.state = "IDLE"
        self.order = None
        self.reason = None
        self.timestamp = None
        self._sm_lock = Lock()

    # =========================
    # STATE TRANSITIONS
    # =========================

    def set_pending(self, order: dict):
        with self._sm_lock:
            self.state = "PENDING_ACTIVE"
            self.order = order
            self.reason = None
            self.timestamp = now_utc()

    def set_cancelled(self, reason: str):
        with self._sm_lock:
            self.state = "CANCELLED"
            self.reason = reason
            self.timestamp = now_utc()

    def set_filled(self, fill_info: dict):
        with self._sm_lock:
            self.state = "FILLED"
            self.order = fill_info
            self.timestamp = now_utc()

    # =========================
    # READ ONLY
    # =========================

    def is_pending(self) -> bool:
        return self.state == "PENDING_ACTIVE"

    def snapshot(self) -> dict:
        return {
            "state": self.state,
            "order": self.order,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
# Placeholder
