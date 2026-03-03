"""
TUYUL FX Wolf-15 — Trade Input API (Write Routes)
=================================================
BUG FIXES APPLIED:
  [BUG-1] Removed APIRouter shadowing class (was overriding FastAPI's APIRouter,
          causing ALL routes to raise NotImplementedError)
  [BUG-2] RiskEngine forward-reference alias moved AFTER class definition in risk_engine.py
  [BUG-3] Redis hardcoded localhost → os.getenv("REDIS_URL") for Railway compatibility
"""

import logging
import contextlib
import threading
import uuid
from datetime import UTC, datetime

import redis as redis_lib
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from redis import Redis

from api.middleware.auth import verify_token
from api.middleware.governance import enforce_write_policy
from allocation.signal_service import SignalService
from accounts.risk_engine import RiskEngine  # noqa: F401
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
from journal.trade_journal_service import trade_journal_automation_service
from infrastructure.tracing import inject_trace_context, setup_tracer
from risk.kill_switch import GlobalKillSwitch

logger = logging.getLogger(__name__)
_allocation_router_tracer = setup_tracer("wolf-api")

# ── [BUG-3 FIX] Redis connection via env var ──────────────────────────────────
def _make_redis() -> Redis | None:
    from infrastructure.redis_url import get_redis_url
    url = get_redis_url()
    return redis_lib.from_url(url, decode_responses=True)  # type: ignore[return-value]


try:
    _redis: Redis | None = _make_redis()
    if _redis:
        from infrastructure.redis_url import get_safe_redis_url

        _redis.ping()
        logger.info("Redis connected: %s", get_safe_redis_url())
except Exception as exc:  # pragma: no cover
    logger.warning("Redis unavailable at startup: %s — using in-memory fallback", exc)
    _redis = None


# ── In-memory fallback stores ─────────────────────────────────────────────────
_signal_pool: dict[str, dict] = {}
_trade_ledger: dict[str, dict] = {}
_account_registry: dict[str, dict] = {}
_signal_service = SignalService()
_kill_switch = GlobalKillSwitch()
_confirm_lock = threading.Lock()

ALLOC_REQUEST_STREAM = "allocation:request"
IDEMPOTENCY_KEY_PREFIX = "idempotency:confirm:"
IDEMPOTENCY_TTL_SEC = 60 * 60 * 24

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


class CloseTradeRequest(BaseModel):
    trade_id: str
    reason: str | None = "MANUAL_CLOSE"
    close_price: float | None = None
    pnl: float | None = None


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

def _redis_set(key: str, value: str, ex: int | None = None) -> None:
    if _redis:
        _redis.set(key, value, ex=ex)


def _redis_get(key: str) -> str | None:
    if _redis:
        val = _redis.get(key)
        return val if isinstance(val, str) else None
    return None


def _redis_hset(name: str, mapping: dict) -> None:
    if _redis:
        _redis.hset(name, mapping=mapping)


def _redis_hgetall(name: str) -> dict:
    if _redis:
        result = _redis.hgetall(name)
        return result if isinstance(result, dict) else {}
    return {}


def _redis_xadd(name: str, fields: dict[str, str]) -> str | None:
    if _redis:
        val = _redis.xadd(name, fields)
        return val if isinstance(val, str) else None
    return None


def _idempotency_get(key: str) -> dict | None:
    import json

    raw = _redis_get(f"{IDEMPOTENCY_KEY_PREFIX}{key}")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _idempotency_set(key: str, response: dict) -> None:
    import json

    _redis_set(
        f"{IDEMPOTENCY_KEY_PREFIX}{key}",
        json.dumps(response),
        ex=IDEMPOTENCY_TTL_SEC,
    )


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


def _build_account_state(account_id: str, account: dict) -> DashAccountState:
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


def _atomic_transition_intended_to_pending(trade_id: str) -> dict:
    import json

    now = datetime.now(UTC).isoformat()
    key = f"TRADE:{trade_id}"

    if _redis:
        try:
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
            result = _redis.eval(script, 1, key, now)
            if isinstance(result, list) and len(result) >= 2 and int(result[0]) == 1:
                payload = str(result[1])
                trade = json.loads(payload)
                _trade_ledger[trade_id] = trade
                return trade

            if isinstance(result, list) and len(result) >= 2:
                state = str(result[1])
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
            raw = _redis_get(key)
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
        _redis_set(key, json.dumps(trade), ex=86400)
        return trade


async def _confirm_trade_internal(trade_id: str, idempotency_key: str | None) -> dict:
    if _kill_switch.is_enabled():
        state = _kill_switch.snapshot()
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Global kill switch is active: {state.get('reason', 'N/A')}",
        )

    if idempotency_key:
        cached = _idempotency_get(idempotency_key)
        if cached:
            return cached

    trade = _atomic_transition_intended_to_pending(trade_id)

    trade_journal_automation_service.on_trade_confirmed(trade)
    with contextlib.suppress(Exception):
        from api.ws_routes import publish_live_update  # noqa: PLC0415

        await publish_live_update("trade_confirmed", trade)

    response = {"trade_id": trade_id, "status": "PENDING"}
    if idempotency_key:
        _idempotency_set(idempotency_key, response)
    return response


# ─── Routes ──────────────────────────────────────────────────────────────────

@write_router.post("/trades/take")
async def take_signal(req: TakeSignalRequest) -> dict:
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

    account = _account_registry.get(req.account_id)
    if not account:
        # Try Redis
        acct_data = _redis_hgetall(f"ACCOUNT:{req.account_id}")
        if not acct_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Account {req.account_id} not found",
            )
        account = acct_data

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
        logger.warning("RiskEngine calculation failed: %s — using fallback", exc)
        risk_result = RiskCalculationResult(
            trade_allowed=True,
            recommended_lot=0.01,
            max_safe_lot=0.01,
            risk_used_percent=0.0,
            daily_dd_after=0.0,
            total_dd_after=0.0,
            severity=RiskSeverity.WARNING,
            reason=f"RiskEngine unavailable: {exc}",
        )

    trade_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    trade = {
        "trade_id": trade_id,
        "signal_id": req.signal_id,
        "account_id": req.account_id,
        "pair": req.pair,
        "direction": req.direction,
        "status": "INTENDED",
        "source": "MANUAL",
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
    _redis_set(f"TRADE:{trade_id}", json.dumps(trade), ex=86400)

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
    _signal_service.publish(signal_payload)
    trade_journal_automation_service.on_signal_taken(trade)

    # Push to live websocket feed (best-effort)
    with contextlib.suppress(Exception):
        from api.ws_routes import publish_live_update  # noqa: PLC0415
        await publish_live_update("trade_intended", trade)
        await publish_live_update("signal", signal_payload)

    logger.info("Trade INTENDED: %s %s %s", trade_id, req.pair, req.direction)
    return {
        "trade_id": trade_id,
        "lot_size": trade["lot_size"],
        "risk_calc": risk_result.model_dump(),
        "status": "INTENDED",
    }


@write_router.post("/signals/take")
async def take_signal_multi(req: TakeSignalBatchRequest) -> dict:
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
        _signal_service.publish(signal_payload)

        queued: list[dict] = []
        for account_id in req.accounts:
            allocation_id = str(uuid.uuid4())
            payload = {
                "request_id": allocation_id,
                "signal_id": req.verdict_id,
                "account_ids": f"[\"{account_id}\"]",
                "operator": req.operator,
                "action": "TAKE",
                "risk_percent": str(req.risk_percent),
            }
            inject_trace_context(payload)
            stream_id = _redis_xadd(ALLOC_REQUEST_STREAM, payload)
            queued.append(
                {
                    "allocation_id": allocation_id,
                    "account_id": account_id,
                    "stream_id": stream_id,
                    "status": "QUEUED" if stream_id else "PENDING_FALLBACK",
                }
            )

    if not _redis:
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
async def skip_signal(req: SkipSignalRequest) -> dict:
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
    _redis_set(f"JOURNAL:{entry_id}", json.dumps(journal_entry), ex=604800)
    trade_journal_automation_service.on_signal_skipped(req.signal_id, req.pair, req.reason or "MANUAL_SKIP")
    with contextlib.suppress(Exception):
        from api.ws_routes import publish_live_update  # noqa: PLC0415
        await publish_live_update("signal_skipped", journal_entry)
    logger.info("Signal SKIPPED: %s %s reason=%s", req.signal_id, req.pair, req.reason)
    return {"logged": True, "entry_id": entry_id, "journal_type": "J2"}


@write_router.post("/signals/skip")
async def skip_signal_alias(req: SkipSignalRequest) -> dict:
    """Compatibility alias for dashboard frontend."""
    return await skip_signal(req)


@write_router.post("/trades/confirm")
async def confirm_trade(
    req: ConfirmTradeRequest,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> dict:
    """Trader confirmed order placement at broker: INTENDED → PENDING."""
    response = await _confirm_trade_internal(req.trade_id, x_idempotency_key)
    logger.info("Trade PENDING: %s", req.trade_id)
    return response


@write_router.post("/trades/{trade_id}/confirm")
async def confirm_trade_by_id(
    trade_id: str,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> dict:
    """Path-parameter variant for dashboard compatibility."""
    response = await _confirm_trade_internal(trade_id, x_idempotency_key)
    logger.info("Trade PENDING (path): %s", trade_id)
    return response


@write_router.post("/trades/close")
async def close_trade(req: CloseTradeRequest) -> dict:
    """Manually close an open trade."""
    import json

    trade = _trade_ledger.get(req.trade_id)
    if not trade:
        raw = _redis_get(f"TRADE:{req.trade_id}")
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
    _redis_set(f"TRADE:{req.trade_id}", json.dumps(trade), ex=604800)
    trade_journal_automation_service.on_trade_closed(trade, req.reason or "MANUAL_CLOSE")
    with contextlib.suppress(Exception):
        from api.ws_routes import publish_live_update  # noqa: PLC0415
        await publish_live_update("trade_closed", trade)

    logger.info("Trade CLOSED: %s reason=%s pnl=%s", req.trade_id, req.reason, req.pnl)
    return {
        "trade_id": req.trade_id,
        "status": "CLOSED",
        "pnl": req.pnl or 0.0,
    }


@write_router.get("/trades/active")
async def get_active_trades() -> dict:
    """Return all non-closed trades."""
    import json

    active = []

    # From in-memory ledger
    for t in _trade_ledger.values():
        if t.get("status") not in ("CLOSED", "CANCELLED", "SKIPPED"):
            active.append(t)

    # From Redis (if available and not already in memory)
    if _redis:
        try:
            for key in _redis.scan_iter("TRADE:*"):
                tid = key.split(":")[-1]
                if tid not in _trade_ledger:
                    raw = _redis.get(key)
                    if raw and isinstance(raw, str):
                        t = json.loads(raw)
                        if t.get("status") not in ("CLOSED", "CANCELLED", "SKIPPED"):
                            active.append(t)
        except Exception as exc:
            logger.warning("Redis scan error: %s", exc)

    return {"trades": active, "count": len(active)}


@write_router.post("/risk/calculate")
async def calculate_risk_preview(req: RiskCalculateRequest) -> dict:
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
        acct_data = _redis_hgetall(f"ACCOUNT:{req.account_id}")
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
