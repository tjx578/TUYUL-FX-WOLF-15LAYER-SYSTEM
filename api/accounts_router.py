"""Read-only API for accounts."""

from fastapi import APIRouter, HTTPException

from dashboard.account_manager import AccountManager

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])

_accounts = AccountManager()


@router.get("")
async def list_accounts() -> dict:
	items = _accounts.list_accounts()
	return {
		"count": len(items),
		"accounts": [a.model_dump() for a in items],
	}


@router.get("/{account_id}")
async def get_account(account_id: str) -> dict:
	account = _accounts.get_account(account_id)
	if not account:
		raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")
	return account.model_dump()
