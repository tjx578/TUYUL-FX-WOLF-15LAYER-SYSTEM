"""
Prop-firm status routes.

Mount scope: dashboard/backend/api.py  (standalone dashboard app)
Do NOT add to api_server.py unless the constitutional/risk routes need extending.
These endpoints expose risk guard output only — no market direction authority.

Limits are read from config/prop_firm.yaml via risk.prop_firm.PropFirmRules.
Per-account phase progress is not yet persisted — see the /phase endpoint note.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from risk.prop_firm import PropFirmRules

router = APIRouter(prefix="/api/v1/prop-firm", tags=["prop-firm"])

_rules: PropFirmRules | None = None


def _get_rules() -> PropFirmRules:
    """Lazy-initialise and cache the PropFirmRules instance."""
    global _rules
    if _rules is None:
        _rules = PropFirmRules()
    return _rules


@router.get("/{account_id}/status")
def get_status(account_id: str) -> dict:
    """Return the active prop-firm rule limits for this account's profile.

    Constitutional constraint: this is a RISK LEGALITY check, not a market
    decision.  account_id is recorded for traceability; the limits come from
    config/prop_firm.yaml (single-profile).  Multi-account profiles are not
    yet implemented.
    """
    try:
        rules = _get_rules()
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Prop-firm config unavailable: {exc}. Check config/prop_firm.yaml.",
        ) from exc

    return {
        "account_id": account_id,
        "allowed": True,
        "code": "LIMITS_OK",
        "details": "Prop-firm limits loaded",
        "max_risk_per_trade_percent": rules.max_risk_allowed(),
        "min_rr_required": rules.min_rr_required(),
        "max_daily_loss": rules.max_daily_loss,
        "max_open_positions": rules.max_open_positions,
        "max_lot_per_trade": rules.max_lot_per_trade,
        "allowed_markets": rules.cfg.get("allowed_markets", {}),
    }


@router.get("/{account_id}/phase")
def get_phase(account_id: str) -> dict:
    """Return the configured prop-firm profile.

    Per-account phase progress (phase-1 / phase-2 / funded) is not yet
    persisted.  Wire to a storage layer (e.g. dashboard ledger) to track
    challenge progress.
    """
    try:
        rules = _get_rules()
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Prop-firm config unavailable: {exc}. Check config/prop_firm.yaml.",
        ) from exc

    prop_cfg: dict = rules.cfg.get("prop_firm", {})
    return {
        "account_id": account_id,
        "firm_name": prop_cfg.get("firm_name", "GENERIC_PROP"),
        "phase_name": "NOT_TRACKED",
        "progress_percent": None,
        "note": (
            "Per-account phase progress is not yet persisted. "
            "Wire to a storage layer to implement challenge-phase tracking."
        ),
    }
