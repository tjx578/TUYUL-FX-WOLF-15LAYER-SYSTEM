"""Read-only API for frozen SignalContract payloads."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query  # noqa: I001

from allocation.signal_service import SignalService
from schemas.signal_contract import FROZEN_SIGNAL_CONTRACT_VERSION

from .middleware.auth import verify_token

router = APIRouter(prefix="/api/v1/signals", tags=["signals"], dependencies=[Depends(verify_token)])

_signals = SignalService()


@router.get("")
async def list_signals(
    symbol: str | None = Query(default=None),  # noqa: W191
    limit: int = Query(default=100, ge=1, le=500),  # noqa: W191
) -> dict:
    items = _signals.list_by_symbol(symbol) if symbol else _signals.list_all()  # noqa: W191
    clipped = items[:limit]  # noqa: W191
    return {  # noqa: W191
        "count": len(clipped),  # noqa: W191
        "contract_version": FROZEN_SIGNAL_CONTRACT_VERSION,  # noqa: W191
        "signals": clipped,  # noqa: W191
    }  # noqa: W191


@router.get("/contract")
async def signal_contract_meta() -> dict:
    return {  # noqa: W191
        "name": "SignalContract",  # noqa: W191
        "frozen": True,  # noqa: W191
        "version": FROZEN_SIGNAL_CONTRACT_VERSION,  # noqa: W191
        "source": "schemas/signal_schema.json",  # noqa: W191
    }  # noqa: W191


@router.get("/{signal_id}")
async def get_signal(signal_id: str) -> dict:
    item = _signals.get(signal_id)  # noqa: W191
    if not item:  # noqa: W191
        raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")  # noqa: W191
    return item  # noqa: W191
