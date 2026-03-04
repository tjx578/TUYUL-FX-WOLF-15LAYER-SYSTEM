"""Accounts API for read + manual CRUD governance."""

from __future__ import annotations

import contextlib
import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api.middleware.governance import enforce_write_policy
from accounts.prop_rule_engine import validate_prop_sovereignty
from dashboard.account_manager import AccountManager
from journal.audit_trail import AuditAction, AuditTrail
from schemas.trade_models import Account
from storage.redis_client import redis_client

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])

_accounts = AccountManager()
_audit = AuditTrail()


class AccountUpsertRequest(BaseModel):
	account_name: str = Field(..., min_length=1, max_length=120)
	broker: str = Field(default="MANUAL", min_length=1, max_length=80)
	currency: str = Field(default="USD", min_length=3, max_length=3)
	starting_balance: float = Field(..., gt=0)
	current_balance: float = Field(..., gt=0)
	equity: float = Field(..., gt=0)
	equity_high: float = Field(..., gt=0)
	leverage: int = Field(default=100, ge=1, le=5000)
	commission_model: str = Field(default="standard", min_length=1, max_length=50)
	notes: str | None = Field(default=None, max_length=300)
	data_source: str = Field(default="MANUAL", pattern="^(EA|MANUAL)$")
	prop_firm: bool = False
	prop_firm_code: str = Field(default="ftmo", min_length=1, max_length=64)
	max_daily_dd_percent: float = Field(default=4.0, gt=0, le=30)
	max_total_dd_percent: float = Field(default=8.0, gt=0, le=50)
	max_concurrent_trades: int = Field(default=1, ge=1, le=20)
	compliance_mode: bool = Field(default=True)
	reason: str = Field(..., min_length=1, max_length=200)


def _validate_compliance_pin_or_raise(*, compliance_mode: bool, x_action_pin: str | None) -> None:
	if compliance_mode:
		return
	expected_pin = os.getenv("DASHBOARD_ACTION_PIN", "").strip()
	if not expected_pin:
		raise HTTPException(status_code=503, detail="Compliance PIN is not configured")
	if (x_action_pin or "").strip() != expected_pin:
		raise HTTPException(status_code=403, detail="Invalid or missing X-Action-Pin for compliance_mode OFF")


def _validate_prop_limits_or_raise(req: AccountUpsertRequest) -> None:
	ok, reason = validate_prop_sovereignty(
		prop_firm_code=req.prop_firm_code,
		max_daily_dd_percent=req.max_daily_dd_percent,
		max_total_dd_percent=req.max_total_dd_percent,
		max_positions=req.max_concurrent_trades,
	)
	if not ok:
		raise HTTPException(status_code=422, detail=reason or "PROP_SOVEREIGNTY_VIOLATION")


def _read_payload(account_id: str) -> dict:
	try:
		return redis_client.client.hgetall(f"ACCOUNT:{account_id}") or {}
	except Exception:
		return {}


def _enrich(account: Account) -> dict:
	payload = _read_payload(account.account_id)
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


@router.get("")
async def list_accounts() -> dict:
	items = _accounts.list_accounts()
	return {
		"count": len(items),
		"accounts": [_enrich(a) for a in items],
	}


@router.get("/risk-snapshot")
async def list_risk_snapshot() -> list[dict]:
	"""Return per-account risk snapshot for Trade Desk governance cards."""
	items = _accounts.list_accounts()
	snapshots: list[dict] = []

	for account in items:
		payload: dict = {}
		try:
			payload = redis_client.client.hgetall(f"ACCOUNT:{account.account_id}") or {}
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
				"max_concurrent": int(account.max_concurrent_trades),
				"open_trades": open_trades,
				"circuit_breaker": circuit_breaker,
				"status": status,
			}
		)

	return snapshots


@router.get("/{account_id}")
async def get_account(account_id: str) -> dict:
	account = _accounts.get_account(account_id)
	if not account:
		raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")
	return _enrich(account)


@router.post("", dependencies=[Depends(enforce_write_policy)])
async def create_account(
	req: AccountUpsertRequest,
	x_action_pin: str | None = Header(default=None, alias="X-Action-Pin"),
) -> dict:
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
	_accounts.upsert_account(account)

	redis_client.client.hset(
		f"ACCOUNT:{account_id}",
		mapping={
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
		},
	)

	_audit.log(
		AuditAction.ORDER_MODIFIED,
		actor="user:dashboard",
		resource=f"account:{account_id}",
		details={"action": "ACCOUNT_CREATE", "reason": req.reason, "data_source": req.data_source},
	)
	return _enrich(account)


@router.put("/{account_id}", dependencies=[Depends(enforce_write_policy)])
async def update_account(
	account_id: str,
	req: AccountUpsertRequest,
	x_action_pin: str | None = Header(default=None, alias="X-Action-Pin"),
) -> dict:
	existing = _accounts.get_account(account_id)
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
		max_daily_dd_percent=req.max_daily_dd_percent,
		max_total_dd_percent=req.max_total_dd_percent,
		max_concurrent_trades=req.max_concurrent_trades,
	)
	_accounts.upsert_account(account)

	redis_client.client.hset(
		f"ACCOUNT:{account_id}",
		mapping={
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
		},
	)

	_audit.log(
		AuditAction.ORDER_MODIFIED,
		actor="user:dashboard",
		resource=f"account:{account_id}",
		details={"action": "ACCOUNT_UPDATE", "reason": req.reason, "data_source": req.data_source},
	)
	return _enrich(account)


class AccountDeleteRequest(BaseModel):
	reason: str = Field(..., min_length=1, max_length=200)


@router.delete("/{account_id}", dependencies=[Depends(enforce_write_policy)])
async def delete_account(account_id: str, req: AccountDeleteRequest) -> dict:
	existing = _accounts.get_account(account_id)
	if not existing:
		raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")

	_accounts._memory_accounts.pop(account_id, None)
	with contextlib.suppress(Exception):
		redis_client.client.delete(f"ACCOUNT:{account_id}")

	_audit.log(
		AuditAction.ORDER_MODIFIED,
		actor="user:dashboard",
		resource=f"account:{account_id}",
		details={"action": "ACCOUNT_DELETE", "reason": req.reason},
	)
	return {"deleted": True, "account_id": account_id}
