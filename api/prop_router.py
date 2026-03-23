"""
Prop-firm status routes.

Mount scope: dashboard/backend/api.py  (standalone dashboard app)
Do NOT add to api_server.py unless the constitutional/risk routes need extending.
These endpoints expose risk guard output only — no market direction authority.

Limits are read from config/prop_firm.yaml via risk.prop_firm.PropFirmRules.
Per-account phase progress is not yet persisted — see the /phase endpoint note.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from propfirm_manager.rule_resolver import PropFirmRuleResolver

from .middleware.auth import verify_token

router = APIRouter(prefix="/api/v1/prop-firm", tags=["prop-firm"], dependencies=[Depends(verify_token)])

# --- New endpoints for prop-firm metadata ---
resolver = PropFirmRuleResolver()


@router.get("/firms")
def list_prop_firms():
    """List all available prop firms."""
    items = []
    for code in resolver.list_firms():
        # Try to get name/description from profile if available
        try:
            profile = resolver._load_profile(code)
            name = profile.get("name", code)
            description = profile.get("description", "")
        except Exception:
            name = code
            description = ""
        items.append({"code": code, "name": name, "description": description})
    return {"items": items}


@router.get("/firms/{firm_code}/programs")
def list_programs_by_firm(firm_code: str):
    """List all programs/plans for a given prop firm."""
    items = []
    for plan in resolver.list_plans(firm_code):
        # Try to get plan details from profile
        try:
            profile = resolver._load_profile(firm_code)
            plans = profile.get("plans", {})
            plan_data = plans.get(plan, {})
            name = plan_data.get("display_name", plan)
            description = plan_data.get("description", "")
            default_phase_code = next(iter(plan_data.get("phases", {})), "funded")
        except Exception:
            name = plan
            description = ""
            default_phase_code = "funded"
        items.append({"code": plan, "name": name, "default_phase_code": default_phase_code, "description": description})
    return {"firm_code": firm_code, "items": items}


@router.get("/firms/{firm_code}/programs/{program_code}/rules")
def preview_resolved_rules(firm_code: str, program_code: str, phase: str = Query("funded")):
    """Preview resolved rules for a given firm/program/phase."""
    try:
        rules = resolver.resolve(firm_code, program_code, phase)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Rules not found: {exc}")

    # Map rules to API contract
    result = {
        "firm_code": firm_code,
        "firm_name": getattr(rules, "firm_name", firm_code),
        "program_code": program_code,
        "program_name": getattr(rules, "program_name", program_code),
        "phase_code": phase,
        "max_daily_dd_percent": getattr(rules, "max_daily_dd_percent", None),
        "drawdown_mode_daily": getattr(rules, "drawdown_mode_daily", None),
        "max_total_dd_percent": getattr(rules, "max_total_dd_percent", None),
        "drawdown_mode_total": getattr(rules, "drawdown_mode_total", None),
        "consistency_rule_percent": getattr(rules, "consistency_rule_percent", None),
        "profit_split_percent": getattr(rules, "profit_split_percent", None),
        "min_trading_days_for_payout": getattr(rules, "min_trading_days_for_payout", None),
        "payout_cycle_days": getattr(rules, "payout_cycle_days", None),
        "leverage": getattr(rules, "leverage", {}),
        "raw_features": getattr(rules, "raw_features", {}),
    }
    return result


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
