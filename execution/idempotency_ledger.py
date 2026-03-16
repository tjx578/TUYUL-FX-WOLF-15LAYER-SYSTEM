from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from loguru import logger

from storage.redis_client import redis_client

_LEDGER_PREFIX = "IDEMPOTENCY:EXECUTION:"
_DEFAULT_TTL_SEC = 60 * 60 * 24


@dataclass(frozen=True)
class LedgerRecord:
    key: str
    signal_id: str
    execution_intent_id: str
    status: str
    created_at: str
    updated_at: str
    payload: dict[str, Any]


class ExecutionIdempotencyLedger:
    """Idempotency ledger keyed by signal_id + execution_intent_id."""

    def __init__(self, ttl_sec: int = _DEFAULT_TTL_SEC) -> None:
        super().__init__()
        self._ttl_sec = max(60, int(ttl_sec))
        self._lock = threading.Lock()
        self._fallback: dict[str, dict[str, Any]] = {}

    @staticmethod
    def compose_key(signal_id: str, execution_intent_id: str) -> str:
        return f"{signal_id.strip()}::{execution_intent_id.strip()}"

    def claim_or_get(
        self,
        *,
        signal_id: str,
        execution_intent_id: str,
        initial_payload: dict[str, Any] | None = None,
    ) -> tuple[bool, LedgerRecord]:
        key = self.compose_key(signal_id, execution_intent_id)
        now = datetime.now(UTC).isoformat()
        initial = {
            "key": key,
            "signal_id": signal_id,
            "execution_intent_id": execution_intent_id,
            "status": "PENDING",
            "created_at": now,
            "updated_at": now,
            "payload": initial_payload or {},
        }

        try:
            redis_key = f"{_LEDGER_PREFIX}{key}"
            ok = redis_client.client.set(redis_key, json.dumps(initial), nx=True, ex=self._ttl_sec)
            if ok:
                return True, self._to_record(initial)
            raw = redis_client.client.get(redis_key)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            if isinstance(raw, str) and raw:
                existing_raw = json.loads(raw)
                if isinstance(existing_raw, dict):
                    existing = cast(dict[str, Any], existing_raw)
                    return False, self._to_record(existing)
        except Exception:
            logger.warning("[IdempotencyLedger] Redis claim_or_get failed for %s", key, exc_info=True)

        with self._lock:
            if key in self._fallback:
                return False, self._to_record(self._fallback[key])
            self._fallback[key] = initial
            return True, self._to_record(initial)

    def mark_success(
        self,
        *,
        signal_id: str,
        execution_intent_id: str,
        payload: dict[str, Any] | None = None,
    ) -> LedgerRecord:
        return self._mark(
            signal_id=signal_id,
            execution_intent_id=execution_intent_id,
            status="SUCCEEDED",
            payload=payload,
        )

    def mark_failed(
        self,
        *,
        signal_id: str,
        execution_intent_id: str,
        payload: dict[str, Any] | None = None,
    ) -> LedgerRecord:
        return self._mark(
            signal_id=signal_id,
            execution_intent_id=execution_intent_id,
            status="FAILED",
            payload=payload,
        )

    def get(self, *, signal_id: str, execution_intent_id: str) -> LedgerRecord | None:
        key = self.compose_key(signal_id, execution_intent_id)
        try:
            raw = redis_client.client.get(f"{_LEDGER_PREFIX}{key}")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            if isinstance(raw, str) and raw:
                data_raw = json.loads(raw)
                if isinstance(data_raw, dict):
                    data = cast(dict[str, Any], data_raw)
                    return self._to_record(data)
        except Exception:
            logger.warning("[IdempotencyLedger] Redis get failed for %s", key, exc_info=True)
        with self._lock:
            item = self._fallback.get(key)
            return self._to_record(item) if item else None

    def _mark(
        self,
        *,
        signal_id: str,
        execution_intent_id: str,
        status: str,
        payload: dict[str, Any] | None,
    ) -> LedgerRecord:
        key = self.compose_key(signal_id, execution_intent_id)
        now = datetime.now(UTC).isoformat()

        existing = self.get(signal_id=signal_id, execution_intent_id=execution_intent_id)
        base_payload = dict(existing.payload) if existing else {}
        if payload:
            base_payload.update(payload)

        updated = {
            "key": key,
            "signal_id": signal_id,
            "execution_intent_id": execution_intent_id,
            "status": status,
            "created_at": existing.created_at if existing else now,
            "updated_at": now,
            "payload": base_payload,
        }

        try:
            redis_client.client.set(
                f"{_LEDGER_PREFIX}{key}",
                json.dumps(updated),
                ex=self._ttl_sec,
            )
        except Exception:
            logger.warning("[IdempotencyLedger] Redis mark failed for %s", key, exc_info=True)

        with self._lock:
            self._fallback[key] = updated
        return self._to_record(updated)

    @staticmethod
    def _to_record(data: dict[str, Any]) -> LedgerRecord:
        return LedgerRecord(
            key=str(data.get("key") or ""),
            signal_id=str(data.get("signal_id") or ""),
            execution_intent_id=str(data.get("execution_intent_id") or ""),
            status=str(data.get("status") or "PENDING"),
            created_at=str(data.get("created_at") or datetime.now(UTC).isoformat()),
            updated_at=str(data.get("updated_at") or datetime.now(UTC).isoformat()),
            payload=dict(data.get("payload") or {}),
        )
