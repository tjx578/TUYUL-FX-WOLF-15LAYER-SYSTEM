"""
Risk Router - Dashboard API Endpoints for Risk Engine v2

Provides REST API for:
- Account risk snapshot
- Signal evaluation
- Risk profile management
- Trade lifecycle tracking
"""

import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from accounts.account_model import (
    AccountState as DashAccountState,
)
from accounts.account_model import (
    Layer12Signal,
    RiskSeverity,
)
from accounts.account_model import (
    RiskMode as DashRiskMode,
)
from accounts.account_repository import AccountRepository, AccountRiskState, EAInstanceConfig
from accounts.prop_rule_engine import get_prop_template, validate_prop_sovereignty
from accounts.risk_calculator import AccountScopedRiskEngine
from accounts.risk_engine import RiskEngine
from allocation.signal_service import SignalService
from api.middleware.governance import enforce_write_policy
from core.redis_keys import compliance_state
from journal.audit_trail import AuditAction, AuditTrail
from risk.exceptions import RiskException
from risk.kill_switch import GlobalKillSwitch
from risk.risk_engine_v2 import RiskEngineV2, SignalInput
from risk.risk_profile import RiskMode, RiskProfile, load_risk_profile, save_risk_profile
from storage.redis_client import redis_client

router = APIRouter(prefix="/api/v1/risk", dependencies=[Depends(enforce_write_policy)])
_kill_switch = GlobalKillSwitch()
_account_repo = AccountRepository.get_default()
_account_risk_engine = AccountScopedRiskEngine()
_audit = AuditTrail()
_account_kill_switches: dict[str, str] = {}
_signal_service = SignalService()


# ========================
# REQUEST/RESPONSE MODELS
# ========================


class RiskProfileRequest(BaseModel):
    """Request to save risk profile."""

    risk_per_trade: float = Field(..., gt=0, le=5.0, description="Risk % per trade")
    max_daily_dd: float = Field(..., gt=0, le=20.0, description="Max daily drawdown %")
    max_total_dd: float = Field(..., gt=0, le=30.0, description="Max total drawdown %")
    max_open_trades: int = Field(..., ge=1, le=5, description="Max concurrent trades")
    risk_mode: str = Field(..., description="FIXED or SPLIT")
    split_ratio: list[float] = Field(default=[0.4, 0.6], description="SPLIT mode ratio")

    @field_validator("risk_mode")
    @classmethod
    def validate_risk_mode(cls, v: str) -> str:
        if v not in ["FIXED", "SPLIT"]:
            raise ValueError("risk_mode must be FIXED or SPLIT")
        return v


class EvaluateSignalRequest(BaseModel):
    """Request to evaluate a trading signal."""

    symbol: str = Field(..., description="Trading pair")
    direction: str = Field(..., description="BUY or SELL")
    entry_price: float = Field(..., gt=0, description="Entry price")
    stop_loss: float = Field(..., gt=0, description="Stop loss price")
    take_profit_1: float = Field(..., gt=0, description="First take profit")
    rr_ratio: float = Field(..., gt=0, description="Risk/reward ratio")
    trade_id: str = Field(..., description="Unique trade ID")
    sl_distance_2: float | None = Field(None, description="Second SL distance for SPLIT")
    vix_level: float | None = Field(None, description="VIX level")
    session: str | None = Field(None, description="Trading session")
    auto_register: bool = Field(default=False, description="Auto-register if ALLOW")

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        if v not in ["BUY", "SELL"]:
            raise ValueError("direction must be BUY or SELL")
        return v


class CloseTradeRequest(BaseModel):
    """Request to close trade tracking."""

    trade_id: str = Field(..., description="Trade ID")
    entry_number: int = Field(default=1, ge=1, le=2, description="Entry number (1 or 2)")


class KillSwitchRequest(BaseModel):
    reason: str = Field(default="MANUAL_KILL_SWITCH", min_length=1, max_length=200)


class AccountContextRequest(BaseModel):
    prop_firm_code: str = Field(..., min_length=1)
    balance: float = Field(..., gt=0)
    equity: float = Field(..., gt=0)
    base_risk_percent: float = Field(..., gt=0, le=5.0)
    max_daily_loss_percent: float = Field(..., gt=0, le=20.0)
    max_total_loss_percent: float = Field(..., gt=0, le=30.0)
    daily_loss_used_percent: float = Field(default=0.0, ge=0, le=100.0)
    total_loss_used_percent: float = Field(default=0.0, ge=0, le=100.0)
    consistency_limit_percent: float = Field(default=0.0, ge=0, le=100.0)
    consistency_used_percent: float = Field(default=0.0, ge=0, le=100.0)
    min_safe_risk_percent: float = Field(default=0.2, ge=0.01, le=2.0)
    account_locked: bool = Field(default=False)
    phase: str = Field(default="PHASE_FUNDED")
    pair_cooldown: dict[str, str] = Field(default_factory=dict)
    max_concurrent_trades: int = Field(default=5, ge=1, le=50)
    open_trades_count: int = Field(default=0, ge=0, le=500)
    correlation_bucket: str = Field(default="GREEN", description="GREEN|YELLOW|RED")
    compliance_mode: bool = Field(default=True)
    news_lock: bool = Field(default=False)
    circuit_breaker_open: bool = Field(default=False)
    system_state: str = Field(default="NORMAL", description="NORMAL|LOCKDOWN")
    ea_connected: bool = Field(default=True)
    abnormal_slippage: bool = Field(default=False)
    daily_dd_block_threshold_percent: float = Field(default=95.0, ge=1.0, le=100.0)
    total_dd_block_threshold_percent: float = Field(default=95.0, ge=1.0, le=100.0)
    ea_instances: list[dict] = Field(default_factory=list)


class AccountTakeRequest(BaseModel):
    signal_id: str = Field(..., min_length=1)
    ea_instance_id: str = Field(..., min_length=1)
    requested_risk_percent: float = Field(..., gt=0, le=5.0)
    stop_loss_pips: float = Field(..., gt=0)
    pip_value_per_lot: float = Field(..., gt=0)
    operator: str = Field(..., min_length=1)
    reason: str = Field(default="TAKE", min_length=1)


class OperatorActionRequest(BaseModel):
    operator: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    old_value: dict | None = None
    new_value: dict | None = None


class PreviewMultiAccount(BaseModel):
    account_id: str = Field(..., min_length=1)


class PreviewMultiRequest(BaseModel):
    verdict_id: str = Field(..., min_length=1)
    accounts: list[PreviewMultiAccount] = Field(..., min_length=1)
    risk_percent: float = Field(default=1.0, gt=0, le=10)
    risk_mode: str = Field(default="FIXED", pattern="^(FIXED|SPLIT)$")


def _pin_matches(x_action_pin: str | None) -> bool:
    expected_pin = os.getenv("DASHBOARD_ACTION_PIN", "").strip()
    if not expected_pin:
        return False
    return (x_action_pin or "").strip() == expected_pin


def _derive_lockdown(req: AccountContextRequest) -> tuple[str, str]:
    if str(req.system_state).strip().upper() == "LOCKDOWN":
        return "LOCKDOWN", "MANUAL_LOCKDOWN"

    if req.daily_loss_used_percent >= req.daily_dd_block_threshold_percent:
        return (
            "LOCKDOWN",
            (
                "DAILY_DD_BLOCK_THRESHOLD: "
                f"{req.daily_loss_used_percent:.2f}% >= {req.daily_dd_block_threshold_percent:.2f}%"
            ),
        )

    if req.total_loss_used_percent >= req.total_dd_block_threshold_percent:
        return (
            "LOCKDOWN",
            (
                "TOTAL_DD_BLOCK_THRESHOLD: "
                f"{req.total_loss_used_percent:.2f}% >= {req.total_dd_block_threshold_percent:.2f}%"
            ),
        )

    if not req.ea_connected:
        return "LOCKDOWN", "EA_DISCONNECTED"

    if req.abnormal_slippage:
        return "LOCKDOWN", "ABNORMAL_SLIPPAGE"

    return "NORMAL", ""


def _runtime_take_guard(state: AccountRiskState) -> tuple[bool, str | None, dict]:
    """Risk governor checks before TAKE. Fail-fast on first hard block."""
    details = {
        "account_id": state.account_id,
        "system_state": state.system_state,
        "daily_dd_used_percent": state.daily_loss_used_percent,
        "total_dd_used_percent": state.total_loss_used_percent,
        "open_trades_count": state.open_trades_count,
        "max_concurrent_trades": state.max_concurrent_trades,
        "correlation_bucket": state.correlation_bucket,
        "news_lock": state.news_lock,
        "compliance_mode": state.compliance_mode,
    }

    if str(state.system_state or "").upper() == "LOCKDOWN":
        details["reason"] = state.lockdown_reason or "LOCKDOWN_ACTIVE"
        return False, "LOCKDOWN_ACTIVE", details

    if not bool(state.compliance_mode):
        details["reason"] = "COMPLIANCE_MODE_DISABLED"
        return False, "COMPLIANCE_MODE_DISABLED", details

    template = get_prop_template(state.prop_firm_code)
    daily_cap = min(float(template.max_daily_loss_percent), float(state.max_daily_loss_percent))
    total_cap = min(float(template.max_total_loss_percent), float(state.max_total_loss_percent))

    if float(state.daily_loss_used_percent) >= daily_cap:
        details["reason"] = f"DAILY_DD_LIMIT {state.daily_loss_used_percent:.2f}% >= {daily_cap:.2f}%"
        return False, "DAILY_DD_LIMIT", details

    if float(state.total_loss_used_percent) >= total_cap:
        details["reason"] = f"TOTAL_DD_LIMIT {state.total_loss_used_percent:.2f}% >= {total_cap:.2f}%"
        return False, "TOTAL_DD_LIMIT", details

    if str(state.correlation_bucket or "GREEN").upper() in {"RED", "BLOCK", "BLOCKED"}:
        details["reason"] = "CORRELATION_BUCKET_BLOCKED"
        return False, "CORRELATION_BUCKET_BLOCKED", details

    if int(state.open_trades_count) >= int(state.max_concurrent_trades):
        details["reason"] = "MAX_OPEN_TRADES"
        return False, "MAX_OPEN_TRADES", details

    if bool(state.news_lock):
        details["reason"] = "NEWS_LOCK"
        return False, "NEWS_LOCK", details

    return True, None, details


def _build_risk_signal(payload: dict, signal_id: str) -> Layer12Signal:
    pair = str(payload.get("symbol") or payload.get("pair") or signal_id.split("_")[0]).upper()
    direction = str(payload.get("direction") or "BUY").upper()
    entry = float(payload.get("entry_price") or payload.get("entry") or 1.0)
    sl = float(payload.get("stop_loss") or entry - 0.0010)
    tp = float(payload.get("take_profit_1") or entry + 0.0020)
    entry_sl_dist = abs(entry - sl)
    rr = abs(tp - entry) / entry_sl_dist if entry_sl_dist > 0 else 1.0

    return Layer12Signal(
        signal_id=uuid.uuid4(),
        timestamp=datetime.now(UTC),
        pair=pair,
        direction="BUY" if direction != "SELL" else "SELL",
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


def _build_account_state(account_id: str) -> DashAccountState:
    payload = redis_client.hgetall(f"ACCOUNT:{account_id}") or {}
    return DashAccountState(
        account_id=account_id,
        balance=float(payload.get("balance", 10000) or 10000),
        equity=float(payload.get("equity", payload.get("balance", 10000)) or 10000),
        equity_high=float(payload.get("equity_high", payload.get("equity", payload.get("balance", 10000))) or 10000),
        daily_dd_percent=float(payload.get("daily_dd_percent", 0.0) or 0.0),
        total_dd_percent=float(payload.get("total_dd_percent", 0.0) or 0.0),
        open_risk_percent=float(payload.get("open_risk_percent", 0.0) or 0.0),
        open_trades=int(payload.get("open_trades", 0) or 0),
        risk_state=RiskSeverity.SAFE,
    )


# ========================
# ENDPOINTS
# ========================


@router.get("/{account_id}/snapshot")
async def get_account_snapshot(
    account_id: str,
    vix_level: float | None = None,
    session: str | None = None,
) -> dict:
    """Get complete account risk snapshot."""
    try:
        engine = RiskEngineV2(account_id)
        snapshot = engine.get_account_snapshot(vix_level=vix_level, session=session)
        return snapshot
    except Exception as exc:
        logger.error("Failed to get account snapshot", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{account_id}/evaluate")
async def evaluate_signal(
    account_id: str,
    req: EvaluateSignalRequest,
) -> dict:
    """
    Evaluate a trading signal against risk constraints.

    Returns ALLOW or DENY verdict with lot sizing details.
    Optionally auto-registers the trade if allowed.
    """
    if _kill_switch.is_enabled():
        state = _kill_switch.snapshot()
        return {
            "verdict": "DENY",
            "deny_code": "GLOBAL_KILL_SWITCH",
            "lots": [],
            "risk_amount": 0.0,
            "open_risk_after": 0.0,
            "open_trades_after": 0,
            "details": state,
        }

    try:
        engine = RiskEngineV2(account_id)
        signal = SignalInput(
            symbol=req.symbol,
            direction=req.direction,
            entry_price=req.entry_price,
            stop_loss=req.stop_loss,
            take_profit_1=req.take_profit_1,
            rr_ratio=req.rr_ratio,
            trade_id=req.trade_id,
            sl_distance_2=req.sl_distance_2,
        )

        result = engine.evaluate(signal, vix_level=req.vix_level, session=req.session)

        # Auto-register if requested and allowed
        if req.auto_register and result.allowed and result.lots is not None:
            engine.register_intended_trade(signal, result.lots)

        return {
            "verdict": result.verdict.value,
            "deny_code": result.deny_code,
            "lots": result.lots,
            "risk_amount": result.risk_amount,
            "open_risk_after": result.open_risk_after,
            "open_trades_after": result.open_trades_after,
            "details": result.details,
        }
    except RiskException as exc:
        logger.warning("Risk evaluation rejected", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to evaluate signal", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{account_id}/profile")
async def save_profile(
    account_id: str,
    req: RiskProfileRequest,
) -> dict:
    """Save risk profile for account."""
    try:
        profile = RiskProfile(
            risk_per_trade=req.risk_per_trade,
            max_daily_dd=req.max_daily_dd,
            max_total_dd=req.max_total_dd,
            max_open_trades=req.max_open_trades,
            risk_mode=RiskMode(req.risk_mode),
            split_ratio=(req.split_ratio[0], req.split_ratio[1]),
        )
        save_risk_profile(account_id, profile)
        return {"status": "saved", "profile": profile.to_dict()}
    except RiskException as exc:
        logger.warning("Invalid risk profile", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to save risk profile", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{account_id}/profile")
async def get_profile(account_id: str) -> dict:
    """Load risk profile for account (returns default if not found)."""
    try:
        profile = load_risk_profile(account_id)
        return profile.to_dict()
    except Exception as exc:
        logger.error("Failed to load risk profile", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{account_id}/close")
async def close_trade(
    account_id: str,
    req: CloseTradeRequest,
) -> dict:
    """Close trade tracking (removes from open exposure)."""
    try:
        engine = RiskEngineV2(account_id)
        engine.close_trade(req.trade_id, req.entry_number)
        return {"status": "closed", "trade_id": req.trade_id, "entry_number": req.entry_number}
    except Exception as exc:
        logger.error("Failed to close trade", account_id=account_id, trade_id=req.trade_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/preview")
async def risk_preview(req: EvaluateSignalRequest) -> dict:
    """Risk Preview payload for modal UI (no trade registration side-effect)."""
    if _kill_switch.is_enabled():
        state = _kill_switch.snapshot()
        return {
            "trade_allowed": False,
            "recommended_lot": 0.0,
            "max_safe_lot": 0.0,
            "reason": f"KILL_SWITCH_ACTIVE: {state.get('reason', 'N/A')}",
            "expiry": None,
            "details": state,
        }

    engine = RiskEngineV2(account_id="preview")
    signal = SignalInput(
        symbol=req.symbol,
        direction=req.direction,
        entry_price=req.entry_price,
        stop_loss=req.stop_loss,
        take_profit_1=req.take_profit_1,
        rr_ratio=req.rr_ratio,
        trade_id=req.trade_id,
        sl_distance_2=req.sl_distance_2,
    )
    result = engine.evaluate(signal, vix_level=req.vix_level, session=req.session)

    lots = result.lots or []
    total_lot = sum(float(item.get("lot_size", 0.0) or 0.0) for item in lots)
    return {
        "trade_allowed": result.allowed,
        "recommended_lot": round(total_lot, 4),
        "max_safe_lot": round(total_lot, 4),
        "reason": result.deny_code or "ALLOW",
        "expiry": None,
        "details": result.details or {},
    }


@router.post("/preview-multi")
async def risk_preview_multi(req: PreviewMultiRequest) -> dict:
    """Batch risk preview per account for multi-account TAKE."""
    if _kill_switch.is_enabled():
        state = _kill_switch.snapshot()
        return {
            "previews": [
                {
                    "account_id": row.account_id,
                    "lot_size": 0.0,
                    "risk_percent": req.risk_percent,
                    "daily_dd_after": 0.0,
                    "allowed": False,
                    "reason": f"KILL_SWITCH_ACTIVE: {state.get('reason', 'N/A')}",
                }
                for row in req.accounts
            ]
        }

    signal_payload = _signal_service.get(req.verdict_id) or {}
    signal = _build_risk_signal(signal_payload, req.verdict_id)
    engine = RiskEngine()

    previews: list[dict] = []
    for row in req.accounts:
        account_state = _build_account_state(row.account_id)
        try:
            result = engine.calculate_lot(
                signal=signal,
                account_state=account_state,
                risk_percent=req.risk_percent,
                prop_firm_code="ftmo",
                risk_mode=DashRiskMode(req.risk_mode),
            )
            preview = {
                "account_id": row.account_id,
                "lot_size": float(result.recommended_lot),
                "risk_percent": float(result.risk_used_percent),
                "daily_dd_after": float(result.daily_dd_after),
                "allowed": bool(result.trade_allowed),
            }
            if result.reason and not result.trade_allowed:
                preview["reason"] = result.reason
            previews.append(preview)
        except Exception as exc:
            previews.append(
                {
                    "account_id": row.account_id,
                    "lot_size": 0.0,
                    "risk_percent": req.risk_percent,
                    "daily_dd_after": 0.0,
                    "allowed": False,
                    "reason": f"RISK_CALC_ERROR: {exc}",
                }
            )

    return {"previews": previews}


@router.get("/kill-switch")
async def get_kill_switch() -> dict:
    return _kill_switch.snapshot()


@router.post("/kill-switch")
async def enable_kill_switch(req: KillSwitchRequest) -> dict:
    return _kill_switch.enable(req.reason)


@router.delete("/kill-switch")
async def disable_kill_switch(req: KillSwitchRequest | None = None) -> dict:
    reason = req.reason if req else "MANUAL_RELEASE"
    return _kill_switch.disable(reason)


@router.post("/accounts/{account_id}/context")
async def upsert_account_context(
    account_id: str,
    req: AccountContextRequest,
    x_action_pin: str | None = Header(default=None, alias="X-Action-Pin"),
) -> dict:
    """Upsert account-scoped risk context for firewall evaluation."""
    ok, reason = validate_prop_sovereignty(
        prop_firm_code=req.prop_firm_code,
        max_daily_dd_percent=req.max_daily_loss_percent,
        max_total_dd_percent=req.max_total_loss_percent,
        max_positions=req.max_concurrent_trades,
    )
    if not ok:
        raise HTTPException(status_code=422, detail=reason or "PROP_SOVEREIGNTY_VIOLATION")

    if not req.compliance_mode and not _pin_matches(x_action_pin):
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing X-Action-Pin for compliance_mode OFF",
        )

    system_state, lockdown_reason = _derive_lockdown(req)

    ea_instances = tuple(
        EAInstanceConfig(
            ea_instance_id=str(item.get("ea_instance_id", "")),
            strategy_profile=str(item.get("strategy_profile", "DEFAULT")),
            risk_multiplier=float(item.get("risk_multiplier", 1.0)),
            news_lock_setting=str(item.get("news_lock_setting", "DEFAULT")),
            enabled=bool(item.get("enabled", True)),
        )
        for item in req.ea_instances
        if str(item.get("ea_instance_id", "")).strip()
    )

    state = AccountRiskState(
        account_id=account_id,
        prop_firm_code=req.prop_firm_code,
        balance=req.balance,
        equity=req.equity,
        base_risk_percent=req.base_risk_percent,
        max_daily_loss_percent=req.max_daily_loss_percent,
        max_total_loss_percent=req.max_total_loss_percent,
        daily_loss_used_percent=req.daily_loss_used_percent,
        total_loss_used_percent=req.total_loss_used_percent,
        consistency_limit_percent=req.consistency_limit_percent,
        consistency_used_percent=req.consistency_used_percent,
        min_safe_risk_percent=req.min_safe_risk_percent,
        account_locked=req.account_locked,
        phase_mode=req.phase,
        pair_cooldown={str(k).upper(): str(v) for k, v in req.pair_cooldown.items()},
        max_concurrent_trades=req.max_concurrent_trades,
        open_trades_count=req.open_trades_count,
        news_lock=req.news_lock,
        correlation_bucket=req.correlation_bucket,
        compliance_mode=req.compliance_mode,
        circuit_breaker_open=req.circuit_breaker_open,
        system_state=system_state,
        lockdown_reason=lockdown_reason,
        ea_connected=req.ea_connected,
        abnormal_slippage=req.abnormal_slippage,
        daily_dd_block_threshold_percent=req.daily_dd_block_threshold_percent,
        total_dd_block_threshold_percent=req.total_dd_block_threshold_percent,
        ea_instances=ea_instances,
    )
    _account_repo.upsert_state(state)
    return {
        "status": "saved",
        "account_id": account_id,
        "system_state": system_state,
        "lockdown_reason": lockdown_reason,
        "compliance_mode": req.compliance_mode,
        "ea_instances": [ea.ea_instance_id for ea in ea_instances],
    }


@router.get("/accounts/{account_id}/buffer")
async def get_account_buffer(account_id: str) -> dict:
    """Return live account buffer for operator awareness."""
    state = _account_repo.get_state(account_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account context not found: {account_id}")

    result = _account_risk_engine.evaluate_trade(
        account_state=state,
        requested_risk_percent=state.base_risk_percent,
        stop_loss_pips=100.0,
        pip_value_per_lot=10.0,
    )
    return {
        "account_id": account_id,
        "daily_buffer_percent": result.daily_buffer_percent,
        "total_buffer_percent": result.total_buffer_percent,
        "consistency_remaining_percent": result.consistency_remaining_percent,
        "max_risk_per_trade_now_percent": result.recommended_risk_percent,
        "status": "SAFE" if result.trade_allowed else "LOCKED",
    }


@router.post("/accounts/{account_id}/take")
async def evaluate_take(account_id: str, req: AccountTakeRequest) -> dict:
    """Evaluate TAKE action with explicit account scope and account firewall."""
    if _kill_switch.is_enabled():
        state = _kill_switch.snapshot()
        return {
            "trade_allowed": False,
            "reason": "GLOBAL_KILL_SWITCH",
            "details": state,
        }

    if account_id in _account_kill_switches:
        return {
            "trade_allowed": False,
            "reason": "ACCOUNT_KILL_SWITCH",
            "details": {"message": _account_kill_switches[account_id]},
        }

    state = _account_repo.get_state(account_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account context not found: {account_id}")

    ea_ids = {ea.ea_instance_id for ea in state.ea_instances if ea.enabled}
    if req.ea_instance_id not in ea_ids:
        return {
            "trade_allowed": False,
            "reason": "EA_INSTANCE_STOPPED_OR_UNKNOWN",
            "details": {"ea_instance_id": req.ea_instance_id},
        }

    runtime_allowed, runtime_reason, runtime_details = _runtime_take_guard(state)
    if not runtime_allowed:
        return {
            "trade_allowed": False,
            "reason": runtime_reason or "RUNTIME_RISK_GOVERNOR",
            "details": runtime_details,
        }

    selected_ea = next(ea for ea in state.ea_instances if ea.ea_instance_id == req.ea_instance_id)
    decision = _account_risk_engine.evaluate_trade(
        account_state=state,
        requested_risk_percent=req.requested_risk_percent,
        stop_loss_pips=req.stop_loss_pips,
        pip_value_per_lot=req.pip_value_per_lot,
        risk_multiplier=selected_ea.risk_multiplier,
    )

    _audit.log(
        AuditAction.ORDER_PLACED if decision.trade_allowed else AuditAction.RISK_CHECK_FAILED,
        actor=f"user:{req.operator}",
        resource=f"account:{account_id}/signal:{req.signal_id}",
        details={
            "action": "TAKE",
            "ea_instance_id": req.ea_instance_id,
            "reason": req.reason,
            "requested_risk_percent": req.requested_risk_percent,
            "decision": {
                "trade_allowed": decision.trade_allowed,
                "status": decision.status,
                "recommended_risk_percent": decision.recommended_risk_percent,
                "recommended_lot": decision.recommended_lot,
                "reason": decision.reason,
            },
        },
    )

    return {
        "account_id": account_id,
        "signal_id": req.signal_id,
        "trade_allowed": decision.trade_allowed,
        "status": decision.status,
        "recommended_risk_percent": decision.recommended_risk_percent,
        "risk_amount": decision.risk_amount,
        "recommended_lot": decision.recommended_lot,
        "max_safe_lot": decision.max_safe_lot,
        "reason": decision.reason,
        "buffer": {
            "daily": decision.daily_buffer_percent,
            "total": decision.total_buffer_percent,
            "consistency": decision.consistency_remaining_percent,
        },
    }


@router.post("/accounts/{account_id}/kill-switch")
async def enable_account_kill_switch(account_id: str, req: KillSwitchRequest) -> dict:
    _account_kill_switches[account_id] = req.reason
    return {"account_id": account_id, "enabled": True, "reason": req.reason}


@router.delete("/accounts/{account_id}/kill-switch")
async def disable_account_kill_switch(account_id: str, req: KillSwitchRequest | None = None) -> dict:
    _account_kill_switches.pop(account_id, None)
    return {
        "account_id": account_id,
        "enabled": False,
        "reason": req.reason if req else "MANUAL_RELEASE",
    }


@router.post("/accounts/{account_id}/operator/skip")
async def operator_skip(account_id: str, req: OperatorActionRequest) -> dict:
    _audit.log(
        AuditAction.SIGNAL_REJECTED,
        actor=f"user:{req.operator}",
        resource=f"account:{account_id}",
        details={"action": "SKIP", "reason": req.reason},
    )
    return {"status": "logged", "action": "SKIP", "account_id": account_id}


@router.post("/accounts/{account_id}/operator/close")
async def operator_close(account_id: str, req: OperatorActionRequest) -> dict:
    _audit.log(
        AuditAction.TRADE_CLOSED,
        actor=f"user:{req.operator}",
        resource=f"account:{account_id}",
        details={"action": "CLOSE", "reason": req.reason},
    )
    return {"status": "logged", "action": "CLOSE", "account_id": account_id}


@router.post("/accounts/{account_id}/operator/change-risk-profile")
async def operator_change_risk_profile(account_id: str, req: OperatorActionRequest) -> dict:
    _audit.log(
        AuditAction.ORDER_MODIFIED,
        actor=f"user:{req.operator}",
        resource=f"account:{account_id}",
        details={
            "action": "CHANGE_RISK_PROFILE",
            "reason": req.reason,
            "old_value": req.old_value or {},
            "new_value": req.new_value or {},
        },
    )
    return {"status": "logged", "action": "CHANGE_RISK_PROFILE", "account_id": account_id}


@router.post("/accounts/{account_id}/operator/change-prop-template")
async def operator_change_prop_template(account_id: str, req: OperatorActionRequest) -> dict:
    _audit.log(
        AuditAction.ORDER_MODIFIED,
        actor=f"user:{req.operator}",
        resource=f"account:{account_id}",
        details={
            "action": "CHANGE_PROP_TEMPLATE",
            "reason": req.reason,
            "old_value": req.old_value or {},
            "new_value": req.new_value or {},
        },
    )
    return {"status": "logged", "action": "CHANGE_PROP_TEMPLATE", "account_id": account_id}


# ── Compliance auto-mode (P1-9) ──────────────────────────────────────────────


@router.get("/accounts/{account_id}/compliance")
async def get_compliance_status(account_id: str) -> dict:
    """Return current compliance mode and DD usage for an account."""
    state = _account_repo.get_state(account_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")

    from risk.compliance_engine import ComplianceAutoModeEngine, ComplianceMode  # noqa: PLC0415

    engine = ComplianceAutoModeEngine()
    result = engine.evaluate(
        account_id=account_id,
        daily_loss_used_percent=state.daily_loss_used_percent,
        max_daily_loss_percent=state.max_daily_loss_percent,
        total_loss_used_percent=state.total_loss_used_percent,
        max_total_loss_percent=state.max_total_loss_percent,
        current_mode=ComplianceMode.NORMAL,
        daily_dd_block_threshold_percent=state.daily_dd_block_threshold_percent,
        total_dd_block_threshold_percent=state.total_dd_block_threshold_percent,
    )
    return {
        "account_id": account_id,
        "compliance_mode": result.current_mode.value,
        "daily_usage_percent": round(result.daily_usage_percent, 2),
        "total_usage_percent": round(result.total_usage_percent, 2),
        "reason": result.reason,
        "thresholds": {
            "warn": result.daily_threshold_warn,
            "block_daily": result.daily_threshold_block,
            "block_total": result.total_threshold_block,
        },
    }


@router.post("/accounts/{account_id}/compliance/evaluate")
async def evaluate_compliance(account_id: str) -> dict:
    """Evaluate compliance mode and emit event if changed. Idempotent."""
    state = _account_repo.get_state(account_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")

    from risk.compliance_engine import ComplianceAutoModeEngine, ComplianceMode  # noqa: PLC0415

    engine = ComplianceAutoModeEngine()
    # Read current persisted mode from Redis if available
    current_mode = ComplianceMode.NORMAL
    try:
        import json as _json  # noqa: PLC0415

        raw = redis_client.get(compliance_state(account_id))
        if raw:
            cached = _json.loads(raw)
            current_mode = ComplianceMode(cached.get("mode", "NORMAL"))
    except Exception:
        pass

    result = await engine.evaluate_and_emit(
        account_id=account_id,
        daily_loss_used_percent=state.daily_loss_used_percent,
        max_daily_loss_percent=state.max_daily_loss_percent,
        total_loss_used_percent=state.total_loss_used_percent,
        max_total_loss_percent=state.max_total_loss_percent,
        current_mode=current_mode,
        daily_dd_block_threshold_percent=state.daily_dd_block_threshold_percent,
        total_dd_block_threshold_percent=state.total_dd_block_threshold_percent,
    )
    return {
        "account_id": account_id,
        "previous_mode": result.previous_mode.value,
        "current_mode": result.current_mode.value,
        "changed": result.changed,
        "reason": result.reason,
    }
