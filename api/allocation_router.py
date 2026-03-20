"""
TUYUL FX Wolf-15 — Trade Input API (Write Routes)
=================================================
BUG FIXES APPLIED:
  [BUG-1] Removed APIRouter shadowing class (was overriding FastAPI's APIRouter,
          causing ALL routes to raise NotImplementedError)
  [BUG-2] RiskEngine forward-reference alias moved AFTER class definition in risk_engine.py
  [BUG-3] Redis hardcoded localhost → os.getenv("REDIS_URL") for Railway compatibility
"""

import contextlib
import hashlib
import logging
import os
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from accounts.account_model import (
    AccountState as DashAccountState,
)
from accounts.account_model import (
    Layer12Signal,
    RiskCalculationResult,
    RiskSeverity,
)
from accounts.account_model import (
    RiskMode as DashRiskMode,
)
from accounts.risk_engine import RiskEngine  # noqa: F401
from allocation.signal_service import SignalService
from api.middleware.governance import enforce_write_policy
from config_loader import load_pairs
from execution.idempotency_ledger import ExecutionIdempotencyLedger
from infrastructure.redis_client import get_client
from infrastructure.tracing import inject_trace_context, setup_tracer
from journal.forensic_replay import append_replay_artifact
from journal.trade_journal_service import trade_journal_automation_service
from risk.kill_switch import GlobalKillSwitch
from state.data_freshness import (
    FeedFreshnessSnapshot,
    classify_feed_freshness,
    stale_threshold_config,
    stale_threshold_seconds,
)
from storage.trade_write_through import persist_trade_snapshot

from .middleware.auth import verify_token

logger = logging.getLogger(__name__)
_allocation_router_tracer = setup_tracer("wolf-api")

# Stale-data threshold: reject write actions if context data is older than this.
STALE_DATA_THRESHOLD_SEC = int(stale_threshold_seconds())
# Grace period after pipeline recovery: allow first fresh verdict through even if
# age slightly exceeds the stale threshold (prevents the post-outage death spiral).
RECOVERY_GRACE_SEC = int(os.getenv("STALE_RECOVERY_GRACE_SEC", "120"))
PRODUCER_REQUIRED_STATES = {"no_producer", "no_transport"}


# ── In-memory fallback stores ─────────────────────────────────────────────────
_signal_pool: dict[str, dict[str, Any]] = {}
_trade_ledger: dict[str, dict[str, Any]] = {}
_account_registry: dict[str, dict[str, Any]] = {}
_signal_service: SignalService | None = None
_kill_switch = GlobalKillSwitch()
_confirm_lock = threading.Lock()
_execution_idempotency = ExecutionIdempotencyLedger()


class _TradeJournalAutomationServiceProtocol(Protocol):
    def on_signal_taken(self, trade: dict[str, Any]) -> None: ...

    def on_trade_confirmed(self, trade: dict[str, Any]) -> None: ...

    def on_signal_skipped(self, signal_id: str, pair: str, reason: str) -> None: ...

    def on_trade_closed(self, trade: dict[str, Any], reason: str) -> None: ...


_journal_service = cast(_TradeJournalAutomationServiceProtocol, trade_journal_automation_service)

ALLOC_REQUEST_STREAM = "allocation:request"
IDEMPOTENCY_KEY_PREFIX = "idempotency:confirm:"
IDEMPOTENCY_TTL_SEC = 60 * 60 * 24
TRADE_OUTBOX_STREAM = "trade:outbox"


def _append_forensic_artifact(
    artifact_type: str,
    *,
    correlation_id: str,
    payload: dict[str, Any],
) -> None:
    with contextlib.suppress(Exception):
        append_replay_artifact(
            artifact_type,
            correlation_id=correlation_id,
            payload=payload,
        )


def _get_signal_service() -> SignalService:
    """Lazily create SignalService so app boot does not require Redis."""
    global _signal_service
    if _signal_service is None:
        try:
            _signal_service = SignalService()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Signal service unavailable: {exc}",
            ) from exc
    return _signal_service


async def _ensure_live_producer(pair: str) -> None:
    """Reject new trade entry when the live producer signal is absent."""
    snapshot = await _feed_freshness_snapshot(pair)
    if snapshot.state in PRODUCER_REQUIRED_STATES:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                f"LIVE_PRODUCER_REQUIRED: {pair} feed state is {snapshot.state} "
                f"({snapshot.detail}). No new trades allowed until producer recovers."
            ),
        )


async def _check_stale_data(pair: str) -> None:
    """Reject write actions if the cached L12 verdict/context data is stale.

    Reads the verdict timestamp from Redis (or the L12 cache) and compares
    it against ``STALE_DATA_THRESHOLD_SEC``.  Raises 409 if stale.

    A ``RECOVERY_GRACE_SEC`` window is applied after the threshold: verdicts
    whose age falls between ``STALE_DATA_THRESHOLD_SEC`` and
    ``STALE_DATA_THRESHOLD_SEC + RECOVERY_GRACE_SEC`` are allowed through
    with a warning.  This prevents the post-outage death spiral where the
    first fresh verdict after a pipeline restart is immediately rejected.
    """
    if STALE_DATA_THRESHOLD_SEC <= 0:
        return

    verdict_ts: float | None = None
    try:
        from storage.l12_cache import get_verdict_async  # noqa: PLC0415

        verdict = await get_verdict_async(pair.upper())
        if verdict:
            ts_raw = verdict.get("timestamp") or verdict.get("ts") or verdict.get("updated_at")
            if ts_raw:
                if isinstance(ts_raw, int | float):
                    verdict_ts = float(ts_raw)
                elif isinstance(ts_raw, str):
                    from datetime import datetime as _dt  # noqa: PLC0415

                    parsed = _dt.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    verdict_ts = parsed.replace(tzinfo=parsed.tzinfo or UTC).timestamp()
    except Exception as exc:
        logger.debug("Stale data check skipped: %s", exc)

    if verdict_ts is not None:
        age = datetime.now(UTC).timestamp() - verdict_ts
        # Logic: check freshness first (early return avoids nesting), then
        # grace period, then hard reject.  Equivalent to:
        #   if age > threshold AND age > threshold+grace: reject
        if age <= STALE_DATA_THRESHOLD_SEC:
            return  # Fresh — proceed

        # Verdict is stale. Check if it falls within the recovery grace window:
        # the first verdict after a pipeline restart may be slightly over threshold
        # but should still be allowed through to break the rejection cycle.
        if age <= STALE_DATA_THRESHOLD_SEC + RECOVERY_GRACE_SEC:
            logger.warning(
                "[StaleGuard] %s verdict age=%.0fs exceeds threshold=%ds "
                "but within recovery grace=%ds — allowing execution",
                pair,
                age,
                STALE_DATA_THRESHOLD_SEC,
                RECOVERY_GRACE_SEC,
            )
            return  # Grace period — allow

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"STALE_DATA: verdict for {pair} is {int(age)}s old "
            f"(threshold: {STALE_DATA_THRESHOLD_SEC}s). Refresh context first.",
        )


# ── [BUG-1 FIX] Use FastAPI's APIRouter directly — no shadowing ───────────────
write_router = APIRouter(
    prefix="/api/v1",
    tags=["trade-write"],
    dependencies=[Depends(verify_token), Depends(enforce_write_policy)],
)


# ─── Pydantic request/response models ────────────────────────────────────────


class TakeSignalRequest(BaseModel):
    signal_id: str
    account_id: str
    pair: str
    direction: str = Field(..., pattern="^(BUY|SELL)$")
    entry: float
    sl: float
    tp: float
    risk_percent: float = Field(default=1.0, gt=0, le=10)
    risk_mode: str = Field(default="FIXED", pattern="^(FIXED|SPLIT)$")
    split_ratio: float | None = Field(default=None, gt=0, le=1)


class TakeSignalBatchRequest(BaseModel):
    verdict_id: str
    accounts: list[str] = Field(..., min_length=1)
    pair: str
    direction: str = Field(..., pattern="^(BUY|SELL)$")
    entry: float
    sl: float
    tp: float
    risk_percent: float = Field(default=1.0, gt=0, le=10)
    operator: str = Field(default="operator")


class SkipSignalRequest(BaseModel):
    signal_id: str
    pair: str
    reason: str | None = "MANUAL_SKIP"


class ConfirmTradeRequest(BaseModel):
    trade_id: str
    execution_intent_id: str | None = None


class CloseTradeRequest(BaseModel):
    trade_id: str
    reason: str | None = "MANUAL_CLOSE"
    close_price: float | None = None
    pnl: float | None = None


class TradeLifecycleEventRequest(BaseModel):
    trade_id: str
    event_type: str = Field(
        ...,
        pattern="^(ORDER_PLACED|ORDER_FILLED|ORDER_CANCELLED|ORDER_EXPIRED|SYSTEM_VIOLATION)$",
    )
    source: str = Field(default="EA", pattern="^(EA|MANUAL)$")
    order_id: str | None = None
    fill_price: float | None = None
    pnl: float | None = None
    reason: str | None = None
    metadata: dict[str, Any] | None = None
    execution_intent_id: str | None = None


class RiskCalculateRequest(BaseModel):
    account_id: str
    pair: str
    direction: str = Field(..., pattern="^(BUY|SELL)$")
    entry: float
    sl: float
    tp: float
    risk_percent: float = Field(default=1.0, gt=0, le=10)
    risk_mode: str = Field(default="FIXED", pattern="^(FIXED|SPLIT)$")


# ─── Helper: Redis read/write with in-memory fallback ────────────────────────


async def _redis_set(key: str, value: str, ex: int | None = None) -> bool:
    try:
        redis = cast(Any, await get_client())
        await redis.set(key, value, ex=ex)
        return True
    except Exception as exc:
        logger.debug("Redis SET fallback for %s: %s", key, exc)
        return False


async def _redis_get(key: str) -> str | None:
    try:
        redis = cast(Any, await get_client())
        val = await redis.get(key)
        return val if isinstance(val, str) else None
    except Exception as exc:
        logger.debug("Redis GET fallback for %s: %s", key, exc)
        return None


async def _redis_hgetall(name: str) -> dict[str, Any]:
    try:
        redis = cast(Any, await get_client())
        result = await redis.hgetall(name)
        return cast(dict[str, Any], result) if isinstance(result, dict) else {}
    except Exception as exc:
        logger.debug("Redis HGETALL fallback for %s: %s", name, exc)
        return {}


async def _redis_xadd(name: str, fields: dict[str, str]) -> str | None:
    try:
        redis = cast(Any, await get_client())
        val = await redis.xadd(name, cast(dict[Any, Any], fields))
        return val if isinstance(val, str) else None
    except Exception as exc:
        logger.debug("Redis XADD fallback for %s: %s", name, exc)
        return None


async def _idempotency_get(key: str) -> dict[str, Any] | None:
    import json

    raw = await _redis_get(f"{IDEMPOTENCY_KEY_PREFIX}{key}")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        return cast(dict[str, Any], payload) if isinstance(payload, dict) else None
    except Exception:
        return None


async def _idempotency_set(key: str, response: dict[str, Any]) -> None:
    import json

    await _redis_set(
        f"{IDEMPOTENCY_KEY_PREFIX}{key}",
        json.dumps(response),
        ex=IDEMPOTENCY_TTL_SEC,
    )


async def _persist_trade_write_through(
    trade: dict[str, Any],
    *,
    event_type: str | None = None,
    event_payload: dict[str, Any] | None = None,
) -> bool:
    """Best-effort PostgreSQL write-through for trade lifecycle changes."""
    with contextlib.suppress(Exception):
        return await persist_trade_snapshot(
            trade,
            event_type=event_type,
            event_payload=event_payload,
        )
    return False


def _intent_from_parts(*parts: str) -> str:
    raw = "::".join([p.strip() for p in parts if p and p.strip()])
    if not raw:
        raw = str(uuid.uuid4())
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


async def _enqueue_outbox_atomic(
    *,
    trade: dict[str, Any],
    event_type: str,
    topic: str,
    payload: dict[str, Any],
) -> str | None:
    import json

    outbox_id = str(uuid.uuid4())
    trade_key = f"TRADE:{trade.get('trade_id')}"
    now = datetime.now(UTC).isoformat()
    event = {
        "outbox_id": outbox_id,
        "topic": topic,
        "event_type": event_type,
        "status": "PENDING",
        "created_at": now,
        "payload": payload,
    }

    try:
        redis = cast(Any, await get_client())
        script = """
        local trade_key = KEYS[1]
        local outbox_stream = KEYS[2]
        local trade_json = ARGV[1]
        local outbox_json = ARGV[2]
        redis.call('SET', trade_key, trade_json, 'EX', 604800)
        return redis.call('XADD', outbox_stream, '*', 'event', outbox_json)
        """
        result = await redis.eval(
            script,
            2,
            trade_key,
            TRADE_OUTBOX_STREAM,
            json.dumps(trade),
            json.dumps(event),
        )
        if isinstance(result, str):
            return result
    except Exception as exc:
        logger.warning("Outbox enqueue failed for trade %s: %s", trade.get("trade_id"), exc)
    return None


# ─── Helper: RiskEngine signal/account construction ─────────────────────────


def _build_risk_signal(
    pair: str,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
) -> Layer12Signal:
    """Build a Layer12Signal for lot-size calculation from raw trade params."""
    entry_sl_dist = abs(entry - sl)
    rr = abs(tp - entry) / entry_sl_dist if entry_sl_dist > 0 else 1.0
    return Layer12Signal(
        signal_id=uuid.uuid4(),
        timestamp=datetime.now(UTC),
        pair=pair,
        direction=direction,
        entry=entry,
        stop_loss=sl,
        take_profit_1=tp,
        rr=rr,
        verdict=f"EXECUTE_{direction}",
        confidence="HIGH",
        wolf_score=0,
        tii_sym=0.0,
        frpc=0.0,
    )


def _build_account_state(account_id: str, account: dict[str, Any]) -> DashAccountState:
    """Build a DashAccountState for lot-size calculation from account dict."""
    return DashAccountState(
        account_id=account_id,
        balance=float(account.get("balance", 10000)),
        equity=float(account.get("equity", 10000)),
        equity_high=float(account.get("equity_high", account.get("equity", 10000))),
        daily_dd_percent=float(account.get("daily_dd_percent", 0)),
        total_dd_percent=float(account.get("total_dd_percent", 0)),
        open_risk_percent=float(account.get("open_risk_percent", 0)),
        open_trades=int(account.get("open_trades", 0)),
        risk_state=RiskSeverity.SAFE,
    )


def _as_bool(raw: object, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled"}


async def _global_news_lock_enabled() -> bool:
    try:
        redis = await get_client()
        return bool(await redis.get("NEWS_LOCK:STATE"))
    except Exception:
        return False


async def _feed_freshness_snapshot(pair: str = "") -> FeedFreshnessSnapshot:
    """Return feed staleness based on latest tick heartbeat in Redis.

    Reads ``wolf15:latest_tick:{symbol}`` HSET keys written by
    ``RedisContextBridge.write_tick()``.  Returns the staleness of the
    *freshest* tick across all configured pairs (best-case metric).
    """
    try:
        redis = cast(Any, await get_client())
        import json as _json  # noqa: PLC0415

        symbols: list[str] = []
        pair_norm = str(pair or "").strip().upper()
        if pair_norm:
            symbols = [pair_norm]
        else:
            pairs = load_pairs()
            symbols = [str(p.get("symbol", "")).strip().upper() for p in pairs if p.get("symbol")]

        threshold_seconds, config_ok = stale_threshold_config()

        if not symbols:
            return classify_feed_freshness(
                transport_ok=True,
                has_producer_signal=False,
                staleness_seconds=float("inf"),
                threshold_seconds=threshold_seconds,
                config_ok=config_ok,
            )

        best_last_seen_ts: float | None = None
        has_tick = False

        for symbol in symbols:
            # P0: Read `last_seen_ts` hash field directly — this is the
            # authoritative write-time timestamp set by RedisContextBridge.
            # Falls back to `timestamp` inside the JSON data payload.
            last_seen_raw = await redis.hget(f"wolf15:latest_tick:{symbol}", "last_seen_ts")
            ts: float = 0.0
            if last_seen_raw:
                try:
                    ts = float(last_seen_raw if isinstance(last_seen_raw, str) else last_seen_raw.decode("utf-8"))
                except (TypeError, ValueError):
                    ts = 0.0

            if ts <= 0:
                data_raw = await redis.hget(f"wolf15:latest_tick:{symbol}", "data")
                if not data_raw:
                    continue
                if isinstance(data_raw, bytes):
                    data_raw = data_raw.decode("utf-8", errors="ignore")
                payload = _json.loads(data_raw) if isinstance(data_raw, str) else {}
                if not isinstance(payload, dict):
                    continue
                ts = float(payload.get("timestamp", 0.0) or 0.0)

            if ts <= 0:
                continue
            has_tick = True
            if best_last_seen_ts is None or ts > best_last_seen_ts:
                best_last_seen_ts = ts

        return classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=has_tick,
            last_seen_ts=best_last_seen_ts,
            now_ts=datetime.now(UTC).timestamp(),
            threshold_seconds=threshold_seconds,
            config_ok=config_ok,
        )
    except Exception:
        threshold_seconds, config_ok = stale_threshold_config()
        return classify_feed_freshness(
            transport_ok=False,
            has_producer_signal=False,
            staleness_seconds=float("inf"),
            threshold_seconds=threshold_seconds,
            config_ok=config_ok,
        )


async def _feed_staleness_seconds(pair: str = "") -> float:
    snapshot = await _feed_freshness_snapshot(pair)
    return snapshot.staleness_seconds


async def _runtime_take_precheck(account: dict[str, Any], pair: str = "") -> tuple[bool, str | None]:
    # Compliance mode default = ON (fail closed when explicitly OFF).
    if not _as_bool(account.get("compliance_mode", 1), default=True):
        return False, "COMPLIANCE_MODE_DISABLED"

    if str(account.get("system_state", "NORMAL")).strip().upper() == "LOCKDOWN":
        reason = str(account.get("lockdown_reason") or "LOCKDOWN_ACTIVE")
        return False, f"LOCKDOWN_ACTIVE: {reason}"

    daily_dd = float(account.get("daily_dd_percent", 0) or 0)
    daily_cap = float(account.get("max_daily_dd_percent", 5.0) or 5.0)
    feed_snapshot = await _feed_freshness_snapshot(pair)
    _append_forensic_artifact(
        "freshness_snapshot",
        correlation_id=str(pair or "GLOBAL").upper(),
        payload={
            "pair": str(pair or "").upper(),
            "state": feed_snapshot.state,
            "freshness_class": feed_snapshot.freshness_class.value,
            "staleness_seconds": feed_snapshot.staleness_seconds,
            "threshold_seconds": feed_snapshot.threshold_seconds,
            "last_seen_ts": feed_snapshot.last_seen_ts,
            "detail": feed_snapshot.detail,
            "account_id": str(account.get("account_id") or ""),
        },
    )
    _kill_switch.evaluate_and_trip(
        metrics={
            "daily_dd_percent": daily_dd,
            "feed_stale_seconds": feed_snapshot.staleness_seconds,
            "feed_freshness_state": feed_snapshot.state,
        }
    )
    if _kill_switch.is_enabled():
        state = _kill_switch.snapshot()
        return False, f"KILL_SWITCH_ACTIVE: {state.get('reason', 'N/A')}"

    if daily_dd >= daily_cap:
        return False, f"DAILY_DD_LIMIT {daily_dd:.2f}% >= {daily_cap:.2f}%"

    total_dd = float(account.get("total_dd_percent", 0) or 0)
    total_cap = float(account.get("max_total_dd_percent", 10.0) or 10.0)
    if total_dd >= total_cap:
        return False, f"TOTAL_DD_LIMIT {total_dd:.2f}% >= {total_cap:.2f}%"

    correlation_bucket = str(account.get("correlation_bucket", "GREEN")).strip().upper()
    if correlation_bucket in {"RED", "BLOCK", "BLOCKED"}:
        return False, "CORRELATION_BUCKET_BLOCKED"

    open_trades = int(account.get("open_trades", 0) or 0)
    max_open = int(account.get("max_concurrent_trades", 1) or 1)
    if open_trades >= max_open:
        return False, f"MAX_OPEN_TRADES {open_trades}/{max_open}"

    if _as_bool(account.get("news_lock", 0), default=False) or await _global_news_lock_enabled():
        return False, "NEWS_LOCK"

    return True, None


async def _atomic_transition_intended_to_pending(trade_id: str) -> dict[str, Any]:
    import json

    now = datetime.now(UTC).isoformat()
    key = f"TRADE:{trade_id}"

    try:
        redis = cast(Any, await get_client())
        script = """
        local key = KEYS[1]
        local now = ARGV[1]
        local raw = redis.call('GET', key)
        if not raw then
          return {0, 'NOT_FOUND'}
        end
        local trade = cjson.decode(raw)
        local current = tostring(trade['status'] or '')
        if current ~= 'INTENDED' then
          return {0, current}
        end
        trade['status'] = 'PENDING'
        trade['updated_at'] = now
        redis.call('SET', key, cjson.encode(trade), 'EX', 86400)
        return {1, cjson.encode(trade)}
        """
        result_raw = await redis.eval(script, 1, key, now)
        if isinstance(result_raw, list):
            result = cast(list[object], result_raw)
            if len(result) >= 2:
                ok_raw = result[0]
                payload_or_state_raw = result[1]

                ok_int = 0
                if isinstance(ok_raw, bool):
                    ok_int = 1 if ok_raw else 0
                elif isinstance(ok_raw, int):
                    ok_int = ok_raw
                elif isinstance(ok_raw, float):
                    ok_int = int(ok_raw)
                elif isinstance(ok_raw, str):
                    with contextlib.suppress(ValueError):
                        ok_int = int(ok_raw)

                if ok_int == 1:
                    if not isinstance(payload_or_state_raw, str):
                        raise HTTPException(
                            status_code=500,
                            detail="Invalid Redis response payload type",
                        )
                    trade = json.loads(payload_or_state_raw)
                    _trade_ledger[trade_id] = trade
                    return trade

                state = payload_or_state_raw if isinstance(payload_or_state_raw, str) else str(payload_or_state_raw)
                if state == "NOT_FOUND":
                    raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
                raise HTTPException(
                    status_code=409,
                    detail=f"Trade {trade_id} is {state}, must be INTENDED to confirm",
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Atomic Redis confirm fallback triggered for %s: %s", trade_id, exc)

    with _confirm_lock:
        trade = _trade_ledger.get(trade_id)
        if not trade:
            raw = await _redis_get(key)
            if not raw:
                raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
            trade = json.loads(raw)

        if trade.get("status") != "INTENDED":
            raise HTTPException(
                status_code=409,
                detail=f"Trade {trade_id} is {trade.get('status')}, must be INTENDED to confirm",
            )

        trade["status"] = "PENDING"
        trade["updated_at"] = now
        _trade_ledger[trade_id] = trade
        await _redis_set(key, json.dumps(trade), ex=86400)
        return trade


async def _confirm_trade_internal(
    trade_id: str,
    idempotency_key: str | None,
    execution_intent_id: str | None = None,
) -> dict[str, Any]:
    if _kill_switch.is_enabled():
        state = _kill_switch.snapshot()
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Global kill switch is active: {state.get('reason', 'N/A')}",
        )

    if idempotency_key:
        cached = await _idempotency_get(idempotency_key)
        if cached:
            return cached

    # Stale-data guard: check trade pair freshness before confirming
    trade_data = _trade_ledger.get(trade_id)
    if not trade_data:
        raw = await _redis_get(f"TRADE:{trade_id}")
        if raw:
            import json as _json  # noqa: PLC0415

            with contextlib.suppress(Exception):
                trade_data = _json.loads(raw)
    if trade_data and trade_data.get("pair"):
        await _check_stale_data(trade_data["pair"])

    signal_id = str((trade_data or {}).get("signal_id") or trade_id)
    intent_id = execution_intent_id or str((trade_data or {}).get("execution_intent_id") or "")
    if not intent_id:
        intent_id = _intent_from_parts(signal_id, trade_id, "ORDER_PLACED")

    claimed, existing = _execution_idempotency.claim_or_get(
        signal_id=signal_id,
        execution_intent_id=intent_id,
        initial_payload={"trade_id": trade_id, "event_type": "ORDER_PLACED"},
    )
    if not claimed and existing.status == "SUCCEEDED":
        cached_resp = dict(existing.payload.get("response") or {})
        if cached_resp:
            return cached_resp

    trade = await _atomic_transition_intended_to_pending(trade_id)
    trade["execution_intent_id"] = intent_id
    persisted = await _persist_trade_write_through(
        trade,
        event_type="ORDER_PLACED",
        event_payload={"source": "MANUAL", "outbox_topic": "trade_confirmed", "execution_intent_id": intent_id},
    )
    if not persisted:
        _execution_idempotency.mark_failed(
            signal_id=signal_id,
            execution_intent_id=intent_id,
            payload={"reason": "PERSIST_FAILED", "trade_id": trade_id},
        )
        raise HTTPException(status_code=503, detail="Failed to persist trade confirmation")

    await _enqueue_outbox_atomic(
        trade=trade,
        event_type="ORDER_PLACED",
        topic="trade_confirmed",
        payload={"trade": trade},
    )
    _append_forensic_artifact(
        "execution_lifecycle",
        correlation_id=intent_id,
        payload={
            "trade_id": trade_id,
            "signal_id": signal_id,
            "event_type": "ORDER_PLACED",
            "source": "MANUAL",
            "status": trade.get("status"),
            "execution_intent_id": intent_id,
        },
    )
    _append_forensic_artifact(
        "event_history",
        correlation_id=intent_id,
        payload={
            "category": "trade_event",
            "trade_id": trade_id,
            "signal_id": signal_id,
            "event_type": "ORDER_PLACED",
            "status": trade.get("status"),
            "source": "MANUAL",
        },
    )

    _journal_service.on_trade_confirmed(trade)
    with contextlib.suppress(Exception):
        from api.ws_routes import publish_live_update  # noqa: PLC0415

        await publish_live_update("trade_confirmed", trade)

    response = {"trade_id": trade_id, "status": "PENDING", "execution_intent_id": intent_id}
    _execution_idempotency.mark_success(
        signal_id=signal_id,
        execution_intent_id=intent_id,
        payload={"response": response, "trade_id": trade_id, "event_type": "ORDER_PLACED"},
    )
    if idempotency_key:
        await _idempotency_set(idempotency_key, response)
    return response


def _apply_trade_event_transition(current_status: str, event_type: str) -> tuple[str, bool]:
    current = str(current_status or "INTENDED").upper()
    mapping: dict[str, dict[str, str]] = {
        "INTENDED": {
            "ORDER_PLACED": "PENDING",
            "SYSTEM_VIOLATION": "ABORTED",
        },
        "PENDING": {
            "ORDER_PLACED": "PENDING",
            "ORDER_FILLED": "OPEN",
            "ORDER_CANCELLED": "CANCELLED",
            "ORDER_EXPIRED": "CANCELLED",
            "SYSTEM_VIOLATION": "ABORTED",
        },
        "OPEN": {
            "ORDER_FILLED": "OPEN",
            "SYSTEM_VIOLATION": "ABORTED",
        },
        "CANCELLED": {
            "ORDER_CANCELLED": "CANCELLED",
            "ORDER_EXPIRED": "CANCELLED",
        },
        "ABORTED": {
            "SYSTEM_VIOLATION": "ABORTED",
        },
    }

    next_status = mapping.get(current, {}).get(event_type)
    if next_status is None:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid trade transition: {current} + {event_type}",
        )

    replay = next_status == current
    return next_status, replay


# ─── Routes ──────────────────────────────────────────────────────────────────


@write_router.post("/trades/take")
async def take_signal(req: TakeSignalRequest) -> dict[str, Any]:
    """
    Create a trade from an L12 EXECUTE signal.
    Lot size is calculated by RiskEngine — never from user input.
    """
    if _kill_switch.is_enabled():
        state = _kill_switch.snapshot()
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Global kill switch is active: {state.get('reason', 'N/A')}",
        )

    await _ensure_live_producer(req.pair)
    await _check_stale_data(req.pair)

    account = _account_registry.get(req.account_id)
    if not account:
        # Try Redis
        acct_data = await _redis_hgetall(f"ACCOUNT:{req.account_id}")
        if not acct_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Account {req.account_id} not found",
            )
        account = acct_data

    precheck_ok, precheck_reason = await _runtime_take_precheck(account, pair=req.pair)
    if not precheck_ok:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"TAKE blocked by runtime risk governor: {precheck_reason}",
        )

    # Risk calculation via RiskEngine
    risk_result: RiskCalculationResult
    try:
        engine = RiskEngine()
        risk_result = engine.calculate_lot(
            signal=_build_risk_signal(req.pair, req.direction, req.entry, req.sl, req.tp),
            account_state=_build_account_state(req.account_id, account),
            risk_percent=req.risk_percent,
            prop_firm_code=str(account.get("prop_firm_code", "ftmo")),
            risk_mode=DashRiskMode(req.risk_mode),
        )
    except Exception as exc:
        logger.error("RiskEngine calculation failed: %s", exc)
        risk_result = RiskCalculationResult(
            trade_allowed=False,
            recommended_lot=0.0,
            max_safe_lot=0.0,
            risk_used_percent=0.0,
            daily_dd_after=0.0,
            total_dd_after=0.0,
            severity=RiskSeverity.CRITICAL,
            reason=f"RiskEngine unavailable: {exc}",
        )

    if not risk_result.trade_allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"TAKE rejected by risk engine: {risk_result.reason or 'RISK_REJECTED'}",
        )

    trade_id = str(uuid.uuid4())
    execution_intent_id = _intent_from_parts(req.signal_id, trade_id, "TRADE_INTENDED")
    now = datetime.now(UTC).isoformat()

    trade: dict[str, Any] = {
        "trade_id": trade_id,
        "signal_id": req.signal_id,
        "account_id": req.account_id,
        "pair": req.pair,
        "direction": req.direction,
        "status": "INTENDED",
        "source": "MANUAL",
        "execution_intent_id": execution_intent_id,
        "risk_mode": req.risk_mode,
        "total_risk_percent": req.risk_percent,
        "total_risk_amount": float(account.get("balance", 10000)) * req.risk_percent / 100,
        "lot_size": risk_result.recommended_lot,
        "entry_price": req.entry,
        "stop_loss": req.sl,
        "take_profit": req.tp,
        "legs": [],
        "created_at": now,
        "updated_at": now,
    }

    import json  # noqa: E402

    _trade_ledger[trade_id] = trade
    await _redis_set(f"TRADE:{trade_id}", json.dumps(trade), ex=86400)
    persisted = await _persist_trade_write_through(
        trade,
        event_type="TRADE_INTENDED",
        event_payload={
            "source": "MANUAL",
            "outbox_topic": "trade_intended",
            "execution_intent_id": execution_intent_id,
        },
    )
    if not persisted:
        raise HTTPException(status_code=503, detail="Failed to persist trade intent")

    await _enqueue_outbox_atomic(
        trade=trade,
        event_type="TRADE_INTENDED",
        topic="trade_intended",
        payload={"trade": trade},
    )

    # Freeze + publish read-only signal contract
    signal_payload = {
        "signal_id": req.signal_id,
        "symbol": req.pair,
        "verdict": "EXECUTE",
        "confidence": 0.8,
        "direction": req.direction,
        "entry_price": req.entry,
        "stop_loss": req.sl,
        "take_profit_1": req.tp,
        "risk_reward_ratio": _build_risk_signal(req.pair, req.direction, req.entry, req.sl, req.tp).rr,
    }
    _get_signal_service().publish(signal_payload)
    _journal_service.on_signal_taken(trade)

    # Push to live websocket feed (best-effort)
    with contextlib.suppress(Exception):
        from api.ws_routes import publish_live_update  # noqa: PLC0415

        await publish_live_update("trade_intended", cast(dict[str, object], trade))
        await publish_live_update("signal", cast(dict[str, object], signal_payload))

    logger.info("Trade INTENDED: %s %s %s", trade_id, req.pair, req.direction)
    return {
        "trade_id": trade_id,
        "execution_intent_id": execution_intent_id,
        "lot_size": trade["lot_size"],
        "risk_calc": risk_result.model_dump(),
        "status": "INTENDED",
    }


@write_router.post("/signals/take")
async def take_signal_multi(req: TakeSignalBatchRequest) -> dict[str, Any]:
    """
    Queue multi-account allocation requests (event-driven path).
    One Redis stream message is published per account.
    """
    if _kill_switch.is_enabled():
        state = _kill_switch.snapshot()
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Global kill switch is active: {state.get('reason', 'N/A')}",
        )

    await _ensure_live_producer(req.pair)
    await _check_stale_data(req.pair)

    with _allocation_router_tracer.start_as_current_span("allocation_enqueue") as span:
        span.set_attribute("signal.id", req.verdict_id)
        span.set_attribute("allocation.account_count", len(req.accounts))

        signal_payload = {
            "signal_id": req.verdict_id,
            "symbol": req.pair,
            "verdict": f"EXECUTE_{req.direction}",
            "confidence": 0.8,
            "direction": req.direction,
            "entry_price": req.entry,
            "stop_loss": req.sl,
            "take_profit_1": req.tp,
            "risk_reward_ratio": _build_risk_signal(req.pair, req.direction, req.entry, req.sl, req.tp).rr,
        }
        _get_signal_service().publish(signal_payload)

        queued: list[dict[str, Any]] = []
        for account_id in req.accounts:
            allocation_id = str(uuid.uuid4())
            payload = {
                "request_id": allocation_id,
                "signal_id": req.verdict_id,
                "account_ids": f'["{account_id}"]',
                "operator": req.operator,
                "action": "TAKE",
                "risk_percent": str(req.risk_percent),
            }
            inject_trace_context(payload)
            stream_id = await _redis_xadd(ALLOC_REQUEST_STREAM, payload)
            queued.append(
                {
                    "allocation_id": allocation_id,
                    "account_id": account_id,
                    "stream_id": stream_id,
                    "status": "QUEUED" if stream_id else "PENDING_FALLBACK",
                }
            )

    if not queued or any(item["stream_id"] is None for item in queued):
        raise HTTPException(
            status_code=503,
            detail="Redis stream unavailable; cannot enqueue allocation request",
        )

    return {
        "signal_id": req.verdict_id,
        "queued": queued,
        "count": len(queued),
        "status": "QUEUED",
    }


@write_router.post("/trades/skip")
async def skip_signal(req: SkipSignalRequest) -> dict[str, Any]:
    """Log a skipped signal as J2: NO_TRADE journal entry."""
    entry_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    journal_entry = {
        "entry_id": entry_id,
        "signal_id": req.signal_id,
        "pair": req.pair,
        "action": "SKIP",
        "reason": req.reason,
        "journal_type": "J2",
        "timestamp": now,
    }
    import json

    await _redis_set(f"JOURNAL:{entry_id}", json.dumps(journal_entry), ex=604800)
    _journal_service.on_signal_skipped(req.signal_id, req.pair, req.reason or "MANUAL_SKIP")
    with contextlib.suppress(Exception):
        from api.ws_routes import publish_live_update  # noqa: PLC0415

        await publish_live_update("signal_skipped", cast(dict[str, object], journal_entry))
    logger.info("Signal SKIPPED: %s %s reason=%s", req.signal_id, req.pair, req.reason)
    return {"logged": True, "entry_id": entry_id, "journal_type": "J2"}


@write_router.post("/signals/skip")
async def skip_signal_alias(req: SkipSignalRequest) -> dict[str, Any]:
    """Compatibility alias for dashboard frontend."""
    return await skip_signal(req)


@write_router.post("/trades/confirm")
async def confirm_trade(
    req: ConfirmTradeRequest,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> dict[str, Any]:
    """Trader confirmed order placement at broker: INTENDED → PENDING."""
    response = await _confirm_trade_internal(
        req.trade_id,
        x_idempotency_key,
        req.execution_intent_id,
    )
    logger.info("Trade PENDING: %s", req.trade_id)
    return response


@write_router.post("/trades/{trade_id}/confirm")
async def confirm_trade_by_id(
    trade_id: str,
    execution_intent_id: str | None = None,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> dict[str, Any]:
    """Path-parameter variant for dashboard compatibility."""
    response = await _confirm_trade_internal(trade_id, x_idempotency_key, execution_intent_id)
    logger.info("Trade PENDING (path): %s", trade_id)
    return response


@write_router.post("/trades/close")
async def close_trade(req: CloseTradeRequest) -> dict[str, Any]:
    """Manually close an open trade."""
    import json

    trade = _trade_ledger.get(req.trade_id)
    if not trade:
        raw = await _redis_get(f"TRADE:{req.trade_id}")
        if not raw:
            raise HTTPException(status_code=404, detail=f"Trade {req.trade_id} not found")
        trade = json.loads(raw)

    now = datetime.now(UTC).isoformat()
    trade["status"] = "CLOSED"
    trade["close_reason"] = req.reason
    trade["closed_at"] = now
    trade["updated_at"] = now
    if req.pnl is not None:
        trade["pnl"] = req.pnl

    _trade_ledger[req.trade_id] = trade
    await _redis_set(f"TRADE:{req.trade_id}", json.dumps(trade), ex=604800)
    persisted = await _persist_trade_write_through(
        trade,
        event_type="TRADE_CLOSED",
        event_payload={
            "source": "MANUAL",
            "outbox_topic": "trade_closed",
            "reason": req.reason,
            "close_price": req.close_price,
            "pnl": req.pnl,
            "execution_intent_id": str(trade.get("execution_intent_id") or ""),
        },
    )
    if not persisted:
        raise HTTPException(status_code=503, detail="Failed to persist trade close")

    await _enqueue_outbox_atomic(
        trade=trade,
        event_type="TRADE_CLOSED",
        topic="trade_closed",
        payload={"trade": trade},
    )
    _journal_service.on_trade_closed(trade, req.reason or "MANUAL_CLOSE")
    with contextlib.suppress(Exception):
        from api.ws_routes import publish_live_update  # noqa: PLC0415

        await publish_live_update("trade_closed", trade)

    logger.info("Trade CLOSED: %s reason=%s pnl=%s", req.trade_id, req.reason, req.pnl)
    return {
        "trade_id": req.trade_id,
        "status": "CLOSED",
        "pnl": req.pnl or 0.0,
    }


@write_router.post("/trades/events")
async def record_trade_lifecycle_event(req: TradeLifecycleEventRequest) -> dict[str, Any]:
    """Record broker lifecycle event and persist trade state to Redis + PostgreSQL."""
    import json

    trade = _trade_ledger.get(req.trade_id)
    if not trade:
        raw = await _redis_get(f"TRADE:{req.trade_id}")
        if not raw:
            raise HTTPException(status_code=404, detail=f"Trade {req.trade_id} not found")
        trade = json.loads(raw)

    now = datetime.now(UTC).isoformat()
    event_type = req.event_type
    reason = req.reason or event_type
    signal_id = str(trade.get("signal_id") or req.trade_id)
    execution_intent_id = req.execution_intent_id or _intent_from_parts(
        signal_id,
        req.trade_id,
        event_type,
        str(req.order_id or ""),
    )

    claimed, existing = _execution_idempotency.claim_or_get(
        signal_id=signal_id,
        execution_intent_id=execution_intent_id,
        initial_payload={"trade_id": req.trade_id, "event_type": event_type},
    )
    if not claimed and existing.status == "SUCCEEDED":
        cached_resp = dict(existing.payload.get("response") or {})
        if cached_resp:
            return cached_resp

    current_status = str(trade.get("status") or "INTENDED")
    next_status, replay = _apply_trade_event_transition(current_status, event_type)
    trade["status"] = next_status
    trade["execution_intent_id"] = execution_intent_id

    if next_status in {"CANCELLED", "ABORTED"}:
        trade["close_reason"] = reason
        trade["closed_at"] = now

    if req.fill_price is not None:
        trade["fill_price"] = req.fill_price
    if req.pnl is not None:
        trade["pnl"] = req.pnl

    trade["updated_at"] = now
    _trade_ledger[req.trade_id] = trade
    await _redis_set(f"TRADE:{req.trade_id}", json.dumps(trade), ex=604800)

    persisted = await _persist_trade_write_through(
        trade,
        event_type=event_type,
        event_payload={
            "source": req.source,
            "outbox_topic": "trade_lifecycle",
            "order_id": req.order_id,
            "reason": req.reason,
            "fill_price": req.fill_price,
            "pnl": req.pnl,
            "metadata": req.metadata or {},
            "execution_intent_id": execution_intent_id,
        },
    )
    if not persisted:
        _execution_idempotency.mark_failed(
            signal_id=signal_id,
            execution_intent_id=execution_intent_id,
            payload={"reason": "PERSIST_FAILED", "trade_id": req.trade_id},
        )
        raise HTTPException(status_code=503, detail="Failed to persist lifecycle event")

    await _enqueue_outbox_atomic(
        trade=trade,
        event_type=event_type,
        topic="trade_lifecycle",
        payload={
            "trade_id": req.trade_id,
            "event_type": event_type,
            "status": trade.get("status"),
            "source": req.source,
            "execution_intent_id": execution_intent_id,
        },
    )
    _append_forensic_artifact(
        "execution_lifecycle",
        correlation_id=execution_intent_id,
        payload={
            "trade_id": req.trade_id,
            "signal_id": signal_id,
            "event_type": event_type,
            "status_before": current_status,
            "status_after": trade.get("status"),
            "replay": replay,
            "source": req.source,
            "order_id": req.order_id,
            "reason": reason,
            "fill_price": req.fill_price,
            "pnl": req.pnl,
            "execution_intent_id": execution_intent_id,
        },
    )
    _append_forensic_artifact(
        "event_history",
        correlation_id=execution_intent_id,
        payload={
            "category": "trade_event",
            "trade_id": req.trade_id,
            "signal_id": signal_id,
            "event_type": event_type,
            "status": trade.get("status"),
            "source": req.source,
            "reason": reason,
            "replay": replay,
        },
    )

    # Auto-trip global kill switch on catastrophic loss velocity / DD breach.
    if req.pnl is not None:
        balance = float(trade.get("total_risk_amount", 0.0) or 0.0) + float(req.pnl or 0.0)
        rapid_loss_pct = 0.0
        if balance > 0 and float(req.pnl) < 0:
            rapid_loss_pct = abs(float(req.pnl)) / balance * 100.0
        _kill_switch.evaluate_and_trip(
            metrics={
                "daily_dd_percent": float(trade.get("daily_dd_percent", 0.0) or 0.0),
                "rapid_loss_percent": rapid_loss_pct,
            }
        )

    if event_type in {"ORDER_CANCELLED", "ORDER_EXPIRED", "SYSTEM_VIOLATION"}:
        _journal_service.on_trade_closed(trade, reason)

    with contextlib.suppress(Exception):
        from api.ws_routes import publish_live_update  # noqa: PLC0415

        await publish_live_update(
            "trade_lifecycle",
            cast(
                dict[str, object],
                {
                    "trade_id": req.trade_id,
                    "event_type": event_type,
                    "status": trade.get("status"),
                    "source": req.source,
                },
            ),
        )

    response = {
        "trade_id": req.trade_id,
        "event_type": event_type,
        "status": trade.get("status"),
        "replay": replay,
        "execution_intent_id": execution_intent_id,
        "persisted": True,
    }
    _execution_idempotency.mark_success(
        signal_id=signal_id,
        execution_intent_id=execution_intent_id,
        payload={"response": response, "trade_id": req.trade_id, "event_type": event_type},
    )
    return response


@write_router.get("/trades/active")
async def get_active_trades() -> dict[str, Any]:
    """Return all non-closed trades."""
    import json

    active: list[dict[str, Any]] = []

    # From in-memory ledger
    for t in _trade_ledger.values():
        if t.get("status") not in ("CLOSED", "CANCELLED", "SKIPPED"):
            active.append(t)

    # From Redis (if available and not already in memory)
    try:
        redis = cast(Any, await get_client())
        async for key in redis.scan_iter(match="TRADE:*"):
            key_str = str(key)
            tid = key_str.split(":")[-1]
            if tid not in _trade_ledger:
                raw = await redis.get(key_str)
                if isinstance(raw, str):
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        trade_record = cast(dict[str, Any], parsed)
                        if trade_record.get("status") not in ("CLOSED", "CANCELLED", "SKIPPED"):
                            active.append(trade_record)
    except Exception as exc:
        logger.warning("Redis scan error: %s", exc)

    return {"trades": active, "count": len(active)}


@write_router.post("/risk/calculate")
async def calculate_risk_preview(req: RiskCalculateRequest) -> dict[str, Any]:
    """
    NEW ENDPOINT — Preview lot calculation before TAKE.
    Frontend uses this to show user exact lot + DD impact before confirming.
    Mirrors: dashboard/backend/risk_engine.py → RiskEngine.calculate_lot()
    """
    if _kill_switch.is_enabled():
        state = _kill_switch.snapshot()
        return {
            "account_id": req.account_id,
            "pair": req.pair,
            "direction": req.direction,
            "trade_allowed": False,
            "reason": f"KILL_SWITCH_ACTIVE: {state.get('reason', 'N/A')}",
            "calculation": {
                "trade_allowed": False,
                "recommended_lot": 0.0,
                "max_safe_lot": 0.0,
                "risk_used_percent": 0.0,
                "daily_dd_after": 0.0,
                "total_dd_after": 0.0,
                "severity": "CRITICAL",
                "reason": f"KILL_SWITCH_ACTIVE: {state.get('reason', 'N/A')}",
            },
        }

    account = _account_registry.get(req.account_id)
    if not account:
        acct_data = await _redis_hgetall(f"ACCOUNT:{req.account_id}")
        account = acct_data or {
            "balance": 10000,
            "equity": 10000,
            "daily_dd_percent": 0,
        }

    try:
        engine = RiskEngine()
        result = engine.calculate_lot(
            signal=_build_risk_signal(req.pair, req.direction, req.entry, req.sl, req.tp),
            account_state=_build_account_state(req.account_id, account),
            risk_percent=req.risk_percent,
            prop_firm_code=str(account.get("prop_firm_code", "ftmo")),
            risk_mode=DashRiskMode(req.risk_mode),
        )
        return {
            "account_id": req.account_id,
            "pair": req.pair,
            "direction": req.direction,
            "calculation": result.model_dump(),
        }
    except Exception as exc:
        logger.error("Risk calculation error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Risk engine error: {exc}") from exc
