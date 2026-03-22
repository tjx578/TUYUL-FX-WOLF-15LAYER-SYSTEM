"""Accounts API for read + manual CRUD governance + capital deployment view."""

from __future__ import annotations

import contextlib
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from accounts.capital_deployment import build_readiness
from accounts.prop_rule_engine import validate_prop_sovereignty
from api.middleware.governance import enforce_write_policy
from dashboard.account_manager import AccountManager
from infrastructure.redis_client import get_client
from journal.audit_trail import AuditAction, AuditTrail
from schemas.trade_models import Account

from .middleware.auth import verify_token

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])

_accounts = AccountManager()
_audit = AuditTrail()


class AccountUpsertRequest(BaseModel):
    account_name: str = Field(..., min_length=1, max_length=120)  # noqa: W191
    broker: str = Field(default="MANUAL", min_length=1, max_length=80)  # noqa: W191
    currency: str = Field(default="USD", min_length=3, max_length=3)  # noqa: W191
    starting_balance: float = Field(..., gt=0)  # noqa: W191
    current_balance: float = Field(..., gt=0)  # noqa: W191
    equity: float = Field(..., gt=0)  # noqa: W191
    equity_high: float = Field(..., gt=0)  # noqa: W191
    leverage: int = Field(default=100, ge=1, le=5000)  # noqa: W191
    commission_model: str = Field(default="standard", min_length=1, max_length=50)  # noqa: W191
    notes: str | None = Field(default=None, max_length=300)  # noqa: W191
    data_source: str = Field(default="MANUAL", pattern="^(EA|MANUAL)$")  # noqa: W191
    prop_firm: bool = False  # noqa: W191
    prop_firm_code: str = Field(default="ftmo", min_length=1, max_length=64)  # noqa: W191
    max_daily_dd_percent: float = Field(default=4.0, gt=0, le=30)  # noqa: W191
    max_total_dd_percent: float = Field(default=8.0, gt=0, le=50)  # noqa: W191
    max_concurrent_trades: int = Field(default=1, ge=1, le=20)  # noqa: W191
    compliance_mode: bool = Field(default=True)  # noqa: W191
    reason: str = Field(..., min_length=1, max_length=200)  # noqa: W191


def _validate_compliance_pin_or_raise(*, compliance_mode: bool, x_action_pin: str | None) -> None:
    if compliance_mode:  # noqa: W191
        return  # noqa: W191
    expected_pin = os.getenv("DASHBOARD_ACTION_PIN", "").strip()  # noqa: W191
    if not expected_pin:  # noqa: W191
        raise HTTPException(status_code=503, detail="Compliance PIN is not configured")  # noqa: W191
    if (x_action_pin or "").strip() != expected_pin:  # noqa: W191
        raise HTTPException(status_code=403, detail="Invalid or missing X-Action-Pin for compliance_mode OFF")  # noqa: W191


def _validate_prop_limits_or_raise(req: AccountUpsertRequest) -> None:
    ok, reason = validate_prop_sovereignty(  # noqa: W191
        prop_firm_code=req.prop_firm_code,  # noqa: W191
        max_daily_dd_percent=req.max_daily_dd_percent,  # noqa: W191
        max_total_dd_percent=req.max_total_dd_percent,  # noqa: W191
        max_positions=req.max_concurrent_trades,  # noqa: W191
    )  # noqa: W191
    if not ok:  # noqa: W191
        raise HTTPException(status_code=422, detail=reason or "PROP_SOVEREIGNTY_VIOLATION")  # noqa: W191


async def _delete_account_or_raise(account_id: str) -> None:
    try:  # noqa: W191
        # Remove account from storage via account manager  # noqa: W191
        redis: Any = await get_client()  # noqa: W191
        await redis.delete(f"ACCOUNT:{account_id}")  # noqa: W191
    except Exception as e:  # noqa: W191
        raise HTTPException(status_code=500, detail=f"Failed to delete account: {str(e)}")  # noqa: B904, W191


async def _read_payload(account_id: str) -> dict[str, Any]:
    try:  # noqa: W191
        redis: Any = await get_client()  # noqa: W191
        raw = await redis.hgetall(f"ACCOUNT:{account_id}")  # noqa: W191
        result: dict[str, Any] = dict(raw or {})  # noqa: W191
        return result  # noqa: W191
    except Exception:  # noqa: W191
        return {}  # noqa: W191


async def _enrich(account: Account) -> dict[str, Any]:
    payload = await _read_payload(account.account_id)  # noqa: W191
    return {  # noqa: W191
        **account.model_dump(),  # noqa: W191
        "account_name": payload.get("account_name", account.name),  # noqa: W191
        "broker": payload.get("broker", "MANUAL"),  # noqa: W191
        "currency": payload.get("currency", "USD"),  # noqa: W191
        "starting_balance": float(payload.get("starting_balance", account.balance) or account.balance),  # noqa: W191
        "current_balance": float(payload.get("current_balance", account.balance) or account.balance),  # noqa: W191
        "equity_high": float(payload.get("equity_high", account.equity) or account.equity),  # noqa: W191
        "leverage": int(payload.get("leverage", 100) or 100),  # noqa: W191
        "commission_model": payload.get("commission_model", "standard"),  # noqa: W191
        "notes": payload.get("notes") or None,  # noqa: W191
        "data_source": payload.get("data_source", "MANUAL"),  # noqa: W191
        "prop_firm_code": payload.get("prop_firm_code", "ftmo"),  # noqa: W191
        "compliance_mode": bool(int(payload.get("compliance_mode", 1) or 1)),  # noqa: W191
        "updated_at": payload.get("updated_at"),  # noqa: W191
    }  # noqa: W191


@router.get("", dependencies=[Depends(verify_token)])
async def list_accounts() -> dict[str, Any]:
    items = await _accounts.list_accounts_async()  # noqa: W191
    return {  # noqa: W191
        "count": len(items),  # noqa: W191
        "accounts": [await _enrich(a) for a in items],  # noqa: W191
    }  # noqa: W191


@router.get("/risk-snapshot", dependencies=[Depends(verify_token)])
async def list_risk_snapshot() -> list[dict[str, Any]]:
    """Return per-account risk snapshot for Trade Desk governance cards."""  # noqa: W191
    items = await _accounts.list_accounts_async()  # noqa: W191
    snapshots: list[dict[str, Any]] = []  # noqa: W191
    client: Any = await get_client()  # noqa: W191

    for account in items:  # noqa: W191
        payload: dict[str, Any] = {}  # noqa: W191
        try:  # noqa: W191
            raw = await client.hgetall(f"ACCOUNT:{account.account_id}")  # noqa: W191
            payload = dict(raw or {})  # noqa: W191
        except Exception:  # noqa: W191
            payload = {}  # noqa: W191

        daily_dd_percent = float(payload.get("daily_dd_percent", 0.0) or 0.0)  # noqa: W191
        total_dd_percent = float(payload.get("total_dd_percent", 0.0) or 0.0)  # noqa: W191
        open_risk_percent = float(payload.get("open_risk_percent", 0.0) or 0.0)  # noqa: W191
        open_trades = int(payload.get("open_trades", 0) or 0)  # noqa: W191

        max_daily_dd = float(account.max_daily_dd_percent or 0.0)  # noqa: W191

        status = "SAFE"  # noqa: W191
        if max_daily_dd > 0:  # noqa: W191
            ratio = daily_dd_percent / max_daily_dd  # noqa: W191
            if ratio >= 0.9:  # noqa: W191
                status = "CRITICAL"  # noqa: W191
            elif ratio >= 0.7:  # noqa: W191
                status = "WARNING"  # noqa: W191

        circuit_breaker = bool(int(payload.get("circuit_breaker", 0) or 0))  # noqa: W191

        snapshots.append(  # noqa: W191
            {  # noqa: W191
                "account_id": account.account_id,  # noqa: W191
                "daily_dd_percent": round(daily_dd_percent, 4),  # noqa: W191
                "total_dd_percent": round(total_dd_percent, 4),  # noqa: W191
                "open_risk_percent": round(open_risk_percent, 4),  # noqa: W191
                "max_concurrent": account.max_concurrent_trades,  # noqa: W191
                "open_trades": open_trades,  # noqa: W191
                "circuit_breaker": circuit_breaker,  # noqa: W191
                "status": status,  # noqa: W191
            }  # noqa: W191
        )  # noqa: W191

    return snapshots  # noqa: W191


@router.get("/capital-deployment", dependencies=[Depends(verify_token)])
async def list_capital_deployment() -> dict[str, Any]:
    """Capital deployment view — readiness, usable capital, eligibility per account."""  # noqa: W191
    items = await _accounts.list_accounts_async()  # noqa: W191
    client: Any = await get_client()  # noqa: W191
    deployment: list[dict[str, Any]] = []  # noqa: W191

    for account in items:  # noqa: W191
        payload: dict[str, Any] = {}  # noqa: W191
        try:  # noqa: W191
            raw = await client.hgetall(f"ACCOUNT:{account.account_id}")  # noqa: W191
            payload = dict(raw or {})  # noqa: W191
        except Exception:  # noqa: W191
            payload = {}  # noqa: W191

        readiness = build_readiness(  # noqa: W191
            account.account_id,  # noqa: W191
            payload,  # noqa: W191
            equity=account.equity,  # noqa: W191
            balance=account.balance,  # noqa: W191
            max_daily_dd_percent=float(account.max_daily_dd_percent or 4.0),  # noqa: W191
            max_total_dd_percent=float(account.max_total_dd_percent or 8.0),  # noqa: W191
            max_concurrent_trades=int(account.max_concurrent_trades or 1),  # noqa: W191
            prop_firm=bool(account.prop_firm),  # noqa: W191
        )  # noqa: W191

        enriched = await _enrich(account)  # noqa: W191
        deployment.append(  # noqa: W191
            {  # noqa: W191
                **enriched,  # noqa: W191
                "readiness_score": readiness.readiness_score,  # noqa: W191
                "usable_capital": readiness.usable_capital,  # noqa: W191
                "eligibility_flags": readiness.eligibility_flags,  # noqa: W191
                "lock_reasons": readiness.lock_reasons,  # noqa: W191
            }  # noqa: W191
        )  # noqa: W191

    total_usable = sum(d["usable_capital"] for d in deployment)  # noqa: W191
    avg_readiness = (  # noqa: W191
        sum(d["readiness_score"] for d in deployment) / len(deployment)  # noqa: W191
        if deployment  # noqa: W191
        else 0.0  # noqa: W191
    )  # noqa: W191

    return {  # noqa: W191
        "count": len(deployment),  # noqa: W191
        "total_usable_capital": round(total_usable, 2),  # noqa: W191
        "avg_readiness_score": round(avg_readiness, 4),  # noqa: W191
        "accounts": deployment,  # noqa: W191
    }  # noqa: W191


@router.get("/{account_id}", dependencies=[Depends(verify_token)])
async def get_account(account_id: str) -> dict[str, Any]:
    account = await _accounts.get_account_async(account_id)  # noqa: W191
    if not account:  # noqa: W191
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")  # noqa: W191
    return await _enrich(account)  # noqa: W191


@router.post("", dependencies=[Depends(enforce_write_policy)])
async def create_account(
    req: AccountUpsertRequest,  # noqa: W191
    x_action_pin: str | None = Header(default=None, alias="X-Action-Pin"),  # noqa: W191
) -> dict[str, Any]:
    _validate_compliance_pin_or_raise(compliance_mode=req.compliance_mode, x_action_pin=x_action_pin)  # noqa: W191
    _validate_prop_limits_or_raise(req)  # noqa: W191

    account_id = f"ACC-{uuid.uuid4().hex[:10].upper()}"  # noqa: W191
    account = Account(  # noqa: W191
        account_id=account_id,  # noqa: W191
        name=req.account_name,  # noqa: W191
        balance=req.current_balance,  # noqa: W191
        equity=req.equity,  # noqa: W191
        prop_firm=req.prop_firm,  # noqa: W191
        max_daily_dd_percent=req.max_daily_dd_percent,  # noqa: W191
        max_total_dd_percent=req.max_total_dd_percent,  # noqa: W191
        max_concurrent_trades=req.max_concurrent_trades,  # noqa: W191
    )  # noqa: W191
    await _accounts.upsert_account_async(account)  # noqa: W191

    client: Any = await get_client()  # noqa: W191
    mapping: dict[str, Any] = {  # noqa: W191
        "account_name": req.account_name,  # noqa: W191
        "broker": req.broker,  # noqa: W191
        "currency": req.currency.upper(),  # noqa: W191
        "starting_balance": req.starting_balance,  # noqa: W191
        "current_balance": req.current_balance,  # noqa: W191
        "equity": req.equity,  # noqa: W191
        "equity_high": req.equity_high,  # noqa: W191
        "leverage": req.leverage,  # noqa: W191
        "commission_model": req.commission_model,  # noqa: W191
        "notes": req.notes or "",  # noqa: W191
        "data_source": req.data_source,  # noqa: W191
        "prop_firm_code": req.prop_firm_code.strip().lower(),  # noqa: W191
        "compliance_mode": int(bool(req.compliance_mode)),  # noqa: W191
        "updated_at": datetime.now(UTC).isoformat(),  # noqa: W191
    }  # noqa: W191
    await client.hset(f"ACCOUNT:{account_id}", mapping=mapping)  # noqa: W191

    _audit.log(  # noqa: W191
        AuditAction.ORDER_MODIFIED,  # noqa: W191
        actor="user:dashboard",  # noqa: W191
        resource=f"account:{account_id}",  # noqa: W191
        details={"action": "ACCOUNT_CREATE", "reason": req.reason, "data_source": req.data_source},  # noqa: W191
    )  # noqa: W191
    return await _enrich(account)  # noqa: W191


@router.put("/{account_id}", dependencies=[Depends(enforce_write_policy)])
async def update_account(
    account_id: str,  # noqa: W191
    req: AccountUpsertRequest,  # noqa: W191
    x_action_pin: str | None = Header(default=None, alias="X-Action-Pin"),  # noqa: W191
) -> dict[str, Any]:
    existing = await _accounts.get_account_async(account_id)  # noqa: W191
    if not existing:  # noqa: W191
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")  # noqa: W191

    _validate_compliance_pin_or_raise(compliance_mode=req.compliance_mode, x_action_pin=x_action_pin)  # noqa: W191
    _validate_prop_limits_or_raise(req)  # noqa: W191

    account = Account(  # noqa: W191
        account_id=account_id,  # noqa: W191
        name=req.account_name,  # noqa: W191
        balance=req.current_balance,  # noqa: W191
        equity=req.equity,  # noqa: W191
        prop_firm=req.prop_firm,  # noqa: W191
        max_daily_dd_percent=req.max_daily_dd_percent,  # noqa: W191
        max_total_dd_percent=req.max_total_dd_percent,  # noqa: W191
        max_concurrent_trades=req.max_concurrent_trades,  # noqa: W191
    )  # noqa: W191
    await _accounts.upsert_account_async(account)  # noqa: W191

    client: Any = await get_client()  # noqa: W191
    mapping: dict[str, Any] = {  # noqa: W191
        "account_name": req.account_name,  # noqa: W191
        "broker": req.broker,  # noqa: W191
        "currency": req.currency.upper(),  # noqa: W191
        "starting_balance": req.starting_balance,  # noqa: W191
        "current_balance": req.current_balance,  # noqa: W191
        "equity": req.equity,  # noqa: W191
        "equity_high": req.equity_high,  # noqa: W191
        "leverage": req.leverage,  # noqa: W191
        "commission_model": req.commission_model,  # noqa: W191
        "notes": req.notes or "",  # noqa: W191
        "data_source": req.data_source,  # noqa: W191
        "prop_firm_code": req.prop_firm_code.strip().lower(),  # noqa: W191
        "compliance_mode": int(bool(req.compliance_mode)),  # noqa: W191
        "updated_at": datetime.now(UTC).isoformat(),  # noqa: W191
    }  # noqa: W191
    await client.hset(f"ACCOUNT:{account_id}", mapping=mapping)  # noqa: W191

    _audit.log(  # noqa: W191
        AuditAction.ORDER_MODIFIED,  # noqa: W191
        actor="user:dashboard",  # noqa: W191
        resource=f"account:{account_id}",  # noqa: W191
        details={"action": "ACCOUNT_UPDATE", "reason": req.reason, "data_source": req.data_source},  # noqa: W191
    )  # noqa: W191
    return await _enrich(account)  # noqa: W191


class AccountDeleteRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)  # noqa: W191


@router.delete("/{account_id}", dependencies=[Depends(enforce_write_policy)])
async def delete_account(account_id: str, req: AccountDeleteRequest) -> dict[str, Any]:
    existing = await _accounts.get_account_async(account_id)  # noqa: W191
    if not existing:  # noqa: W191
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")  # noqa: W191

    await _delete_account_or_raise(account_id)  # noqa: W191
    with contextlib.suppress(Exception):  # noqa: W191
        client = await get_client()  # noqa: W191
        await client.delete(f"ACCOUNT:{account_id}")  # noqa: W191

    _audit.log(  # noqa: W191
        AuditAction.ORDER_MODIFIED,  # noqa: W191
        actor="user:dashboard",  # noqa: W191
        resource=f"account:{account_id}",  # noqa: W191
        details={"action": "ACCOUNT_DELETE", "reason": req.reason},  # noqa: W191
    )  # noqa: W191
    return {"deleted": True, "account_id": account_id}  # noqa: W191
