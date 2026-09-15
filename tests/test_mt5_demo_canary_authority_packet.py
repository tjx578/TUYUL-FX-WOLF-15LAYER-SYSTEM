from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from execution.mt5_demo_canary_authority_packet import (
    AuthorityPacketError,
    DemoCanaryAuthorityPacketV1,
    IssuanceDisposition,
    ProcessLocalIssuanceCapability,
    ProcessLocalIssuanceError,
    canonical_packet_bytes,
    command_content_sha256_from_fields,
    load_and_validate_authority_packet,
    packet_sha256,
    validate_authority_packet,
)

NOW = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
COMMAND_ID = UUID("11111111-1111-4111-8111-111111111111")


def _packet(**updates: object) -> DemoCanaryAuthorityPacketV1:
    values: dict[str, object] = {
        "authority_packet_id": "d0-v3-fixture",
        "canary_id": "d0-v3-fixture",
        "approved_by": "operator-fixture",
        "approved_at_utc": NOW - timedelta(minutes=1),
        "command_id": COMMAND_ID,
        "idempotency_key": "account-ref:engineering-demo-canary:d0-v3-fixture:PLACE_MARKET",
        "executor_id": UUID("22222222-2222-4222-8222-222222222222"),
        "expected_account_snapshot_id": "direct-mt5-snapshot-v3",
        "account_reference": "account-ref",
        "broker_server": "DEMO-SERVER",
        "canonical_symbol": "EURUSD",
        "broker_symbol": "EURUSD",
        "side": "BUY",
        "order_type": "BUY",
        "volume": Decimal("0.01"),
        "entry_price": Decimal("1.10000"),
        "stop_loss": Decimal("1.09500"),
        "take_profit": Decimal("1.11000"),
        "issued_at_utc": NOW - timedelta(seconds=1),
        "expires_at_utc": NOW + timedelta(seconds=89),
        "max_spread_points": 30,
        "max_price_drift_points": 20,
        "max_slippage_points": 20,
        "magic_number": 150016,
        "order_check_max": 2,
        "order_send_max": 1,
        "child_allowed": False,
        "automatic_retry": False,
        "max_commands": 1,
        "issuer_source_revision": "132a428106bcc9e9c3e4303f48d6075a77b8a6ab",
    }
    values.update(updates)
    if "command_content_sha256" not in updates:
        values["command_content_sha256"] = command_content_sha256_from_fields(values)
    return DemoCanaryAuthorityPacketV1(**values)  # type: ignore[arg-type]


def test_canonical_digest_is_stable_and_preselected_command_id_is_preserved() -> None:
    packet = _packet()
    raw = canonical_packet_bytes(packet)

    assert packet.command_id == COMMAND_ID
    assert raw == canonical_packet_bytes(packet)
    assert packet_sha256(packet) == packet_sha256(packet.model_copy())
    assert json.loads(raw)["command_id"] == str(COMMAND_ID)


def test_exact_digest_and_active_window_pass() -> None:
    packet = _packet()
    digest = packet_sha256(packet)

    assert validate_authority_packet(packet, expected_sha256=digest, now=NOW) == digest
    assert (
        load_and_validate_authority_packet(packet.model_dump_json().encode(), expected_sha256=digest, now=NOW) == packet
    )


def test_one_field_tamper_is_rejected() -> None:
    packet = _packet()
    original_digest = packet_sha256(packet)
    tampered = packet.model_copy(update={"max_slippage_points": 11})

    with pytest.raises(AuthorityPacketError, match="digest mismatch"):
        validate_authority_packet(tampered, expected_sha256=original_digest, now=NOW)


def test_command_content_hash_rejects_trade_field_tamper_even_with_new_packet_digest() -> None:
    with pytest.raises(ValidationError, match="command_content_sha256"):
        _packet(max_spread_points=31, command_content_sha256=command_content_sha256_from_fields(_packet().model_dump()))


@pytest.mark.parametrize("offset", (-2, 90))
def test_inactive_packet_is_rejected(offset: int) -> None:
    packet = _packet()
    with pytest.raises(AuthorityPacketError, match="not currently active"):
        validate_authority_packet(
            packet,
            expected_sha256=packet_sha256(packet),
            now=NOW + timedelta(seconds=offset),
        )


def test_process_capability_creates_at_most_once_and_then_reports_already_issued() -> None:
    packet = _packet()
    digest = packet_sha256(packet)
    calls = 0

    def issuer(_packet: DemoCanaryAuthorityPacketV1) -> IssuanceDisposition:
        nonlocal calls
        calls += 1
        return IssuanceDisposition.CREATED

    capability = ProcessLocalIssuanceCapability(packet_sha256_value=digest, command_id=COMMAND_ID)
    assert capability.issue_once(packet, expected_sha256=digest, now=NOW, issuer=issuer) is IssuanceDisposition.CREATED
    assert (
        capability.issue_once(packet, expected_sha256=digest, now=NOW, issuer=issuer)
        is IssuanceDisposition.ALREADY_ISSUED
    )
    assert calls == 1
    assert capability.consumed is True


def test_fresh_process_propagates_repository_already_issued() -> None:
    packet = _packet()
    digest = packet_sha256(packet)
    capability = ProcessLocalIssuanceCapability(packet_sha256_value=digest, command_id=COMMAND_ID)

    result = capability.issue_once(
        packet,
        expected_sha256=digest,
        now=NOW,
        issuer=lambda _packet: IssuanceDisposition.ALREADY_ISSUED,
    )

    assert result is IssuanceDisposition.ALREADY_ISSUED
    assert capability.consumed is True


def test_capability_rejects_different_packet_or_command_identity() -> None:
    packet = _packet()
    digest = packet_sha256(packet)
    wrong = _packet(command_id=UUID("33333333-3333-4333-8333-333333333333"))
    wrong_digest = packet_sha256(wrong)
    capability = ProcessLocalIssuanceCapability(packet_sha256_value=digest, command_id=COMMAND_ID)

    with pytest.raises(ProcessLocalIssuanceError, match="outside"):
        capability.issue_once(
            wrong,
            expected_sha256=wrong_digest,
            now=NOW,
            issuer=lambda _packet: IssuanceDisposition.CREATED,
        )


def test_schema_is_frozen_strict_and_forbids_extra_fields() -> None:
    packet = _packet()
    with pytest.raises(ValidationError):
        packet.side = "SELL"  # type: ignore[misc]

    raw = packet.model_dump(mode="json")
    raw["unexpected"] = True
    with pytest.raises(AuthorityPacketError, match="schema validation"):
        load_and_validate_authority_packet(json.dumps(raw).encode(), expected_sha256=packet_sha256(packet), now=NOW)
