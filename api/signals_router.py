"""Read-only API for frozen SignalContract payloads."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query  # noqa: I001

from allocation.signal_service import SignalService
from schemas.signal_contract import FROZEN_SIGNAL_CONTRACT_VERSION

from .middleware.auth import verify_token

router = APIRouter(prefix="/api/v1/signals", tags=["signals"], dependencies=[Depends(verify_token)])

_signals = SignalService()

# ── Allowed verdict prefixes for the execute_only filter ──────────────────
_EXECUTE_VERDICTS = {"EXECUTE", "EXECUTE_BUY", "EXECUTE_SELL", "EXECUTE_REDUCED_RISK"}


def _is_execute(verdict_str: str) -> bool:
    return verdict_str in _EXECUTE_VERDICTS or verdict_str.startswith("EXECUTE")


@router.get("")
async def list_signals(
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    execute_only: bool = Query(default=False, description="Return only EXECUTE* verdicts"),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum confidence threshold"),
    active_only: bool = Query(default=False, description="Exclude expired signals (expires_at in the past)"),
) -> dict:
    items = _signals.list_by_symbol(symbol) if symbol else _signals.list_all()

    now = time.time()
    filtered = []
    for sig in items:
        if execute_only and not _is_execute(str(sig.get("verdict", ""))):
            continue
        if float(sig.get("confidence", 0.0) or 0.0) < min_confidence:
            continue
        if active_only:
            expires = sig.get("expires_at")
            if expires is not None and float(expires) < now:
                continue
        filtered.append(sig)

    clipped = filtered[:limit]
    return {
        "count": len(clipped),
        "contract_version": FROZEN_SIGNAL_CONTRACT_VERSION,
        "signals": clipped,
    }


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
