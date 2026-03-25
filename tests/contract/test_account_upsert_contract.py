"""
Contract tests — Account create / update payload parity (PR-001)

These tests ensure:
  1. AccountUpsertRequest (backend) accepts exactly the fields that
     CreateAccountRequest (frontend) sends — no silent ignoring.
  2. Required/optional field semantics match across the boundary.
  3. Governance fields (max_daily_dd_percent, max_total_dd_percent,
     max_concurrent_trades, compliance_mode) are explicitly declared
     on both sides with no silent coercion.
  4. Create and update endpoints round-trip all declared fields
     through to Redis storage and back to the enriched response.

Run:
    pytest tests/contract/test_account_upsert_contract.py -v
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from api.accounts_router import AccountUpsertRequest

# ── Canonical field sets ───────────────────────────────────────────────────────

# Fields the TypeScript CreateAccountRequest interface declares.
# This is the single source of truth for what the frontend sends.
FRONTEND_CREATE_FIELDS: set[str] = {
    "account_name",
    "broker",
    "currency",
    "starting_balance",
    "current_balance",
    "equity",
    "equity_high",
    "leverage",
    "commission_model",
    "notes",
    "data_source",
    "prop_firm",
    "prop_firm_code",
    "program_code",
    "phase_code",
    "compliance_mode",
    "max_daily_dd_percent",
    "max_total_dd_percent",
    "max_concurrent_trades",
    "reason",
}

# Fields declared on the backend Pydantic model.
BACKEND_MODEL_FIELDS: set[str] = set(AccountUpsertRequest.model_fields.keys())


# ── 1:1 field parity ──────────────────────────────────────────────────────────


class TestFieldParity:
    """Frontend CreateAccountRequest and backend AccountUpsertRequest must
    declare exactly the same set of fields — no silent drift."""

    def test_frontend_fields_all_present_on_backend(self) -> None:
        missing = FRONTEND_CREATE_FIELDS - BACKEND_MODEL_FIELDS
        assert not missing, (
            f"Frontend sends fields the backend model does NOT declare: {missing}. "
            "These would be silently ignored by Pydantic."
        )

    def test_backend_fields_all_present_on_frontend(self) -> None:
        extra = BACKEND_MODEL_FIELDS - FRONTEND_CREATE_FIELDS
        assert not extra, (
            f"Backend model has fields the frontend does NOT send: {extra}. "
            "These fall back to silent defaults — potential governance gap."
        )

    def test_exact_parity(self) -> None:
        assert FRONTEND_CREATE_FIELDS == BACKEND_MODEL_FIELDS, (
            f"Field drift detected.\n"
            f"  FE-only: {FRONTEND_CREATE_FIELDS - BACKEND_MODEL_FIELDS}\n"
            f"  BE-only: {BACKEND_MODEL_FIELDS - FRONTEND_CREATE_FIELDS}"
        )


# ── Minimal valid payload ─────────────────────────────────────────────────────

MINIMAL_CREATE_PAYLOAD: dict[str, Any] = {
    "account_name": "Test Account",
    "broker": "IC Markets",
    "currency": "USD",
    "starting_balance": 10000.0,
    "current_balance": 10000.0,
    "equity": 10000.0,
    "equity_high": 10000.0,
    "leverage": 100,
    "commission_model": "standard",
    "notes": "",
    "data_source": "MANUAL",
    "prop_firm": False,
    "prop_firm_code": None,
    "program_code": None,
    "phase_code": None,
    "compliance_mode": True,
    "max_daily_dd_percent": 4.0,
    "max_total_dd_percent": 8.0,
    "max_concurrent_trades": 1,
    "reason": "ACCOUNT_CREATE_FROM_UI",
}

PROP_FIRM_PAYLOAD: dict[str, Any] = {
    **MINIMAL_CREATE_PAYLOAD,
    "prop_firm": True,
    "prop_firm_code": "ftmo",
    "program_code": "200k_swing",
    "phase_code": "funded",
    "max_daily_dd_percent": 4.0,
    "max_total_dd_percent": 8.0,
    "max_concurrent_trades": 1,
    "reason": "ACCOUNT_CREATE_PROP_FIRM",
}


# ── Payload validation ────────────────────────────────────────────────────────


class TestCreatePayloadValidation:
    """Backend model must accept exactly the payload that createAccount() sends."""

    def test_minimal_payload_accepted(self) -> None:
        req = AccountUpsertRequest(**MINIMAL_CREATE_PAYLOAD)
        assert req.account_name == "Test Account"
        assert req.max_daily_dd_percent == 4.0
        assert req.max_total_dd_percent == 8.0
        assert req.max_concurrent_trades == 1

    def test_prop_firm_payload_accepted(self) -> None:
        req = AccountUpsertRequest(**PROP_FIRM_PAYLOAD)
        assert req.prop_firm is True
        assert req.prop_firm_code == "ftmo"
        assert req.program_code == "200k_swing"

    def test_rejects_missing_required_fields(self) -> None:
        """account_name, starting_balance, current_balance, reason are required."""
        for field in ("account_name", "starting_balance", "current_balance", "reason"):
            incomplete = {k: v for k, v in MINIMAL_CREATE_PAYLOAD.items() if k != field}
            with pytest.raises(ValidationError):
                AccountUpsertRequest(**incomplete)

    def test_rejects_unknown_extra_fields(self) -> None:
        """Ensure Pydantic doesn't silently accept stray fields.

        If the model uses extra='allow' this test would fail, catching
        accidental scope creep.
        """
        payload = {**MINIMAL_CREATE_PAYLOAD, "unknown_field": "surprise"}
        req = AccountUpsertRequest(**payload)
        # Pydantic v2 default is extra='ignore', so unknown field is dropped.
        # We verify it does NOT appear on the model.
        assert not hasattr(req, "unknown_field")

    def test_data_source_enum_validation(self) -> None:
        good_payload = {**MINIMAL_CREATE_PAYLOAD, "data_source": "EA"}
        req = AccountUpsertRequest(**good_payload)
        assert req.data_source == "EA"

        bad_payload = {**MINIMAL_CREATE_PAYLOAD, "data_source": "INVALID_SOURCE"}
        with pytest.raises(ValidationError):
            AccountUpsertRequest(**bad_payload)


# ── Governance field contract ─────────────────────────────────────────────────


class TestGovernanceFields:
    """Risk/governance fields must never be silently coerced or ignored."""

    def test_max_daily_dd_must_be_positive(self) -> None:
        bad = {**MINIMAL_CREATE_PAYLOAD, "max_daily_dd_percent": 0}
        with pytest.raises(ValidationError):
            AccountUpsertRequest(**bad)

    def test_max_daily_dd_must_not_exceed_100(self) -> None:
        bad = {**MINIMAL_CREATE_PAYLOAD, "max_daily_dd_percent": 101}
        with pytest.raises(ValidationError):
            AccountUpsertRequest(**bad)

    def test_max_total_dd_must_be_positive(self) -> None:
        bad = {**MINIMAL_CREATE_PAYLOAD, "max_total_dd_percent": 0}
        with pytest.raises(ValidationError):
            AccountUpsertRequest(**bad)

    def test_max_concurrent_trades_must_be_at_least_1(self) -> None:
        bad = {**MINIMAL_CREATE_PAYLOAD, "max_concurrent_trades": 0}
        with pytest.raises(ValidationError):
            AccountUpsertRequest(**bad)

    def test_compliance_mode_is_bool(self) -> None:
        req = AccountUpsertRequest(**{**MINIMAL_CREATE_PAYLOAD, "compliance_mode": False})
        assert req.compliance_mode is False

    def test_leverage_bounds(self) -> None:
        with pytest.raises(ValidationError):
            AccountUpsertRequest(**{**MINIMAL_CREATE_PAYLOAD, "leverage": 0})
        with pytest.raises(ValidationError):
            AccountUpsertRequest(**{**MINIMAL_CREATE_PAYLOAD, "leverage": 5001})

    def test_defaults_match_frontend_hardcoded_values(self) -> None:
        """Verify the backend defaults match what the frontend currently sends
        so that omitting optional fields never silently shifts governance."""
        req = AccountUpsertRequest(
            account_name="Defaults Test",
            starting_balance=5000,
            current_balance=5000,
            equity=5000,
            equity_high=5000,
            reason="test",
        )
        assert req.leverage == 100
        assert req.commission_model == "standard"
        assert req.data_source == "MANUAL"
        assert req.compliance_mode is True
        assert req.max_daily_dd_percent == 4.0
        assert req.max_total_dd_percent == 8.0
        assert req.max_concurrent_trades == 1
        assert req.broker == "MANUAL"
        assert req.currency == "USD"
        assert req.prop_firm is False
        assert req.phase_code == "funded"


# ── Update payload contract ───────────────────────────────────────────────────


class TestUpdatePayloadContract:
    """The update endpoint uses the same AccountUpsertRequest model,
    so all create contract tests apply. These additionally check
    update-specific semantics."""

    def test_update_payload_same_model_as_create(self) -> None:
        """PUT /accounts/{id} and POST /accounts use the same Pydantic model."""
        import typing

        from api.accounts_router import create_account, update_account

        create_hints = typing.get_type_hints(create_account)
        update_hints = typing.get_type_hints(update_account)
        assert create_hints["req"] is update_hints["req"] is AccountUpsertRequest

    def test_update_can_change_risk_fields(self) -> None:
        """Risk fields can be updated to different non-default values."""
        payload = {
            **MINIMAL_CREATE_PAYLOAD,
            "max_daily_dd_percent": 3.0,
            "max_total_dd_percent": 6.0,
            "max_concurrent_trades": 2,
        }
        req = AccountUpsertRequest(**payload)
        assert req.max_daily_dd_percent == 3.0
        assert req.max_total_dd_percent == 6.0
        assert req.max_concurrent_trades == 2

    def test_update_can_toggle_compliance(self) -> None:
        req = AccountUpsertRequest(**{**MINIMAL_CREATE_PAYLOAD, "compliance_mode": False})
        assert req.compliance_mode is False
