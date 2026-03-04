"""Read-only API for frozen SignalContract payloads."""

from fastapi import APIRouter, Depends, HTTPException, Query

from api.middleware.auth import verify_token
from allocation.signal_service import SignalService
from schemas.signal_contract import FROZEN_SIGNAL_CONTRACT_VERSION

router = APIRouter(prefix="/api/v1/signals", tags=["signals"], dependencies=[Depends(verify_token)])

_signals = SignalService()


@router.get("")
async def list_signals(
	symbol: str | None = Query(default=None),
	limit: int = Query(default=100, ge=1, le=500),
) -> dict:
	items = _signals.list_by_symbol(symbol) if symbol else _signals.list_all()
	clipped = items[:limit]
	return {
		"count": len(clipped),
		"contract_version": FROZEN_SIGNAL_CONTRACT_VERSION,
		"signals": clipped,
	}


@router.get("/contract")
async def signal_contract_meta() -> dict:
	return {
		"name": "SignalContract",
		"frozen": True,
		"version": FROZEN_SIGNAL_CONTRACT_VERSION,
		"source": "schemas/signal_schema.json",
	}


@router.get("/{signal_id}")
async def get_signal(signal_id: str) -> dict:
	item = _signals.get(signal_id)
	if not item:
		raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")
	return item
