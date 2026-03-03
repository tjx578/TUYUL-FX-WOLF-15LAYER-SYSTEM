"""Read-only API for accounts."""

from fastapi import APIRouter, HTTPException

from dashboard.account_manager import AccountManager
from storage.redis_client import redis_client

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])

_accounts = AccountManager()


@router.get("")
async def list_accounts() -> dict:
	items = _accounts.list_accounts()
	return {
		"count": len(items),
		"accounts": [a.model_dump() for a in items],
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
	return account.model_dump()
