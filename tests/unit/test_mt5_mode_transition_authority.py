from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from contracts.mt5_mode_transition_authority import (
    ModeTransitionAuthorityError,
    ModeTransitionAuthorityPacket,
    canonical_mode_transition_authority_sha256,
)

NOW = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)


def _fields(*, previous_mode: str = "SHADOW", new_mode: str = "DEMO") -> dict[str, object]:
    fields: dict[str, object] = {
        "schema_version": "wolf15.mt5.mode-transition-authority.v1",
        "authority_packet_id": "11111111-1111-4111-8111-111111111111",
        "approval_id": "operator-approval-001",
        "approved_by": "operator:owner",
        "approved_at_utc": NOW.isoformat(),
        "expires_at_utc": (NOW + timedelta(minutes=5)).isoformat(),
        "executor_id": "22222222-2222-4222-8222-222222222222",
        "account_reference": "demo-account-binding",
        "broker_server": "XMGlobal-MT5 10",
        "configuration_sha256": f"sha256:{'a' * 64}",
        "final_shadow_receipt_sha256": f"sha256:{'b' * 64}",
        "previous_mode": previous_mode,
        "new_mode": new_mode,
        "consumption_limit": 1,
    }
    fields["authority_packet_sha256"] = canonical_mode_transition_authority_sha256(fields)
    return fields


@pytest.mark.parametrize(
    ("previous_mode", "new_mode"),
    [("SHADOW", "DEMO"), ("DEMO", "SHADOW")],
)
def test_exact_governed_transition_is_canonical_and_one_use_ready(
    previous_mode: str,
    new_mode: str,
) -> None:
    packet = ModeTransitionAuthorityPacket.model_validate(_fields(previous_mode=previous_mode, new_mode=new_mode))

    assert packet.executor_id == UUID("22222222-2222-4222-8222-222222222222")
    assert packet.canonical_sha256() == packet.authority_packet_sha256
    packet.assert_one_use_ready(now_utc=NOW + timedelta(seconds=1), prior_consumptions=0)


def test_tampered_binding_is_rejected_by_canonical_digest() -> None:
    fields = _fields()
    fields["broker_server"] = "different-server"

    with pytest.raises(ValidationError, match="does not match canonical packet bytes"):
        ModeTransitionAuthorityPacket.model_validate(fields)


@pytest.mark.parametrize(
    ("previous_mode", "new_mode"),
    [("SHADOW", "SHADOW"), ("DEMO", "DEMO"), ("SHADOW", "LIVE"), ("LIVE", "SHADOW")],
)
def test_non_governed_transition_shape_is_rejected(previous_mode: str, new_mode: str) -> None:
    with pytest.raises(ValidationError, match="only SHADOW->DEMO and DEMO->SHADOW"):
        ModeTransitionAuthorityPacket.model_validate(_fields(previous_mode=previous_mode, new_mode=new_mode))


def test_consumed_expired_and_not_yet_active_authorities_fail_closed() -> None:
    packet = ModeTransitionAuthorityPacket.model_validate(_fields())

    with pytest.raises(ModeTransitionAuthorityError, match="already consumed"):
        packet.assert_one_use_ready(now_utc=NOW, prior_consumptions=1)
    with pytest.raises(ModeTransitionAuthorityError, match="not active yet"):
        packet.assert_one_use_ready(now_utc=NOW - timedelta(seconds=1), prior_consumptions=0)
    with pytest.raises(ModeTransitionAuthorityError, match="expired"):
        packet.assert_one_use_ready(now_utc=NOW + timedelta(minutes=5), prior_consumptions=0)


def test_packet_is_frozen_and_rejects_missing_binding_or_extra_fields() -> None:
    packet = ModeTransitionAuthorityPacket.model_validate(_fields())
    with pytest.raises(ValidationError, match="frozen"):
        packet.approved_by = "other"  # type: ignore[misc]

    missing = _fields()
    del missing["final_shadow_receipt_sha256"]
    missing["authority_packet_sha256"] = canonical_mode_transition_authority_sha256(missing)
    with pytest.raises(ValidationError, match="final_shadow_receipt_sha256"):
        ModeTransitionAuthorityPacket.model_validate(missing)

    extra = _fields()
    extra["self_promote"] = True
    extra["authority_packet_sha256"] = canonical_mode_transition_authority_sha256(extra)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ModeTransitionAuthorityPacket.model_validate(extra)


def test_naive_times_and_invalid_window_are_rejected() -> None:
    naive = _fields()
    naive["approved_at_utc"] = NOW.replace(tzinfo=None).isoformat()
    with pytest.raises(ValidationError, match="must include a UTC offset"):
        ModeTransitionAuthorityPacket.model_validate(naive)

    invalid = _fields()
    invalid["expires_at_utc"] = NOW.isoformat()
    invalid["authority_packet_sha256"] = canonical_mode_transition_authority_sha256(invalid)
    with pytest.raises(ValidationError, match="must be later"):
        ModeTransitionAuthorityPacket.model_validate(invalid)
