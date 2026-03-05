"""Accounts API for read + manual CRUD governance."""

from __future__ import annotations

import contextlib
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from accounts.prop_rule_engine import validate_prop_sovereignty
from api.middleware.auth import verify_token
from api.middleware.governance import enforce_write_policy
from dashboard.account_manager import AccountManager
from infrastructure.redis_client import get_client
from journal.audit_trail import AuditAction, AuditTrail
from schemas.trade_models import Account

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
		return result
	except Exception:
		return {}


async def _enrich(account: Account) -> dict[str, Any]:
	payload = await _read_payload(account.account_id)
	return {
		**account.model_dump(),
		"account_name": payload.get("account_name", account.name),
		"broker": payload.get("broker", "MANUAL"),
		"currency": payload.get("currency", "USD"),
		"starting_balance": float(payload.get("starting_balance", account.balance) or account.balance),
		"current_balance": float(payload.get("current_balance", account.balance) or account.balance),
		"equity_high": float(payload.get("equity_high", account.equity) or account.equity),
		"leverage": int(payload.get("leverage", 100) or 100),
		"commission_model": payload.get("commission_model", "standard"),
		"notes": payload.get("notes") or None,
		"data_source": payload.get("data_source", "MANUAL"),
		"prop_firm_code": payload.get("prop_firm_code", "ftmo"),
		"compliance_mode": bool(int(payload.get("compliance_mode", 1) or 1)),
		"updated_at": payload.get("updated_at"),
	}


@router.get("", dependencies=[Depends(verify_token)])
async def list_accounts() -> dict[str, Any]:
	items = await _accounts.list_accounts_async()
	return {
		"count": len(items),
		"accounts": [await _enrich(a) for a in items],
	}


@router.get("/risk-snapshot", dependencies=[Depends(verify_token)])
async def list_risk_snapshot() -> list[dict[str, Any]]:
	"""Return per-account risk snapshot for Trade Desk governance cards."""
	items = await _accounts.list_accounts_async()
	snapshots: list[dict[str, Any]] = []
	client: Any = await get_client()

	for account in items:
		payload: dict[str, Any] = {}
		try:
			raw = await client.hgetall(f"ACCOUNT:{account.account_id}")
			payload = dict(raw or {})
		except Exception:
			payload = {}

		daily_dd_percent = float(payload.get("daily_dd_percent", 0.0) or 0.0)
		total_dd_percent = float(payload.get("total_dd_percent", 0.0) or 0.0)
		open_risk_percent = float(payload.get("open_risk_percent", 0.0) or 0.0)
		open_trades = int(payload.get("open_trades", 0) or 0)

		max_daily_dd = float(account.max_daily_dd_percent or 0.0)

		status = "SAFE"
		if max_daily_dd > 0:
			ratio = daily_dd_percent / max_daily_dd
			if ratio >= 0.9:
				status = "CRITICAL"
			elif ratio >= 0.7:
				status = "WARNING"

		circuit_breaker = bool(int(payload.get("circuit_breaker", 0) or 0))

		snapshots.append(
			{
				"account_id": account.account_id,
				"daily_dd_percent": round(daily_dd_percent, 4),
				"total_dd_percent": round(total_dd_percent, 4),
				"open_risk_percent": round(open_risk_percent, 4),
				"max_concurrent": account.max_concurrent_trades,
				"open_trades": open_trades,
				"circuit_breaker": circuit_breaker,
				"status": status,
			}
		)

	return snapshots


@router.get("/{account_id}", dependencies=[Depends(verify_token)])
async def get_account(account_id: str) -> dict[str, Any]:
	account = await _accounts.get_account_async(account_id)
	if not account:
		raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")
	return await _enrich(account)


@router.post("", dependencies=[Depends(enforce_write_policy)])
async def create_account(
	req: AccountUpsertRequest,
	x_action_pin: str | None = Header(default=None, alias="X-Action-Pin"),
) -> dict[str, Any]:
	_validate_compliance_pin_or_raise(compliance_mode=req.compliance_mode, x_action_pin=x_action_pin)
	_validate_prop_limits_or_raise(req)

	account_id = f"ACC-{uuid.uuid4().hex[:10].upper()}"
	account = Account(
		account_id=account_id,
		name=req.account_name,
		balance=req.current_balance,
		equity=req.equity,
		prop_firm=req.prop_firm,
		max_daily_dd_percent=req.max_daily_dd_percent,
		max_total_dd_percent=req.max_total_dd_percent,
		max_concurrent_trades=req.max_concurrent_trades,
	)
	await _accounts.upsert_account_async(account)

	client: Any = await get_client()
	mapping: dict[str, Any] = {
		"account_name": req.account_name,
		"broker": req.broker,
		"currency": req.currency.upper(),
		"starting_balance": req.starting_balance,
		"current_balance": req.current_balance,
		"equity": req.equity,
		"equity_high": req.equity_high,
		"leverage": req.leverage,
		"commission_model": req.commission_model,
		"notes": req.notes or "",
		"data_source": req.data_source,
		"prop_firm_code": req.prop_firm_code.strip().lower(),
		"compliance_mode": int(bool(req.compliance_mode)),
		"updated_at": datetime.now(UTC).isoformat(),
	}
	await client.hset(f"ACCOUNT:{account_id}", mapping=mapping)

	_audit.log(
		AuditAction.ORDER_MODIFIED,
		actor="user:dashboard",
		resource=f"account:{account_id}",
		details={"action": "ACCOUNT_CREATE", "reason": req.reason, "data_source": req.data_source},
	)
	return await _enrich(account)


@router.put("/{account_id}", dependencies=[Depends(enforce_write_policy)])
async def update_account(
	account_id: str,
	req: AccountUpsertRequest,
	x_action_pin: str | None = Header(default=None, alias="X-Action-Pin"),
) -> dict[str, Any]:
	existing = await _accounts.get_account_async(account_id)
	if not existing:
		raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")

	_validate_compliance_pin_or_raise(compliance_mode=req.compliance_mode, x_action_pin=x_action_pin)
	_validate_prop_limits_or_raise(req)

	account = Account(
		account_id=account_id,
		name=req.account_name,
		balance=req.current_balance,
		equity=req.equity,
		prop_firm=req.prop_firm,
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
		actor="user:dashboard",
		resource=f"account:{account_id}",
		details={"action": "ACCOUNT_DELETE", "reason": req.reason},
	)
	return {"deleted": True, "account_id": account_id}
