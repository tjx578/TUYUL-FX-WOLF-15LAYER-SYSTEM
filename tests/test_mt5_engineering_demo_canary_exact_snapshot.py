"""Frozen D0 canary issuance binds the operator-frozen snapshot S, not the latest heartbeat snapshot.

Follow-up to #482: evidence is stored for S; a newer heartbeat snapshot S+1 must not make the
issuance look up evidence for S+1 and reject the valid receipt for S.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from contracts.mt5_execution_protocol import EngineeringDemoCanaryGuards
from execution.broker_reconciliation_evidence import ReconciliationEvidenceError
from execution.mt5_demo_canary_authority_packet import (
    DemoCanaryAuthorityPacketV1,
    IssuanceDisposition,
    ProcessLocalIssuanceCapability,
    command_content_sha256_from_fields,
    packet_sha256,
)
from execution.mt5_engineering_demo_canary import EngineeringDemoCanaryAuthorityV1, EngineeringDemoCanaryError
from tests.reconciliation_fixtures import configure_test_keys, fixture_attestation, fixture_identity
from tests.test_d0_canary_control_capabilities import _packet_values
from tests.test_mt5_engineering_demo_canary import EXECUTOR_ID, SECRET, _FakeRepository, _snapshot


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    configure_test_keys(monkeypatch)
    monkeypatch.setenv("WOLF15_ENABLE_ENGINEERING_DEMO_CANARY_ISSUANCE", "true")
    monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_KEY_ID", "d0-test-key")


class ExactSnapshotRepository(_FakeRepository):
    """Stores S and a newer S+1; evidence exists only for S."""

    def __init__(
        self, *, bound_age_seconds: float = 12.0, evidence_for: str | None = "snapshot-S", newer: dict | None = None
    ) -> None:
        super().__init__()
        now = datetime.now(UTC)
        self.bound = _snapshot(snapshot_id="snapshot-S", captured_at_utc=now - timedelta(seconds=bound_age_seconds))
        self.newer = _snapshot(snapshot_id="snapshot-S1", captured_at_utc=now, **(newer or {}))
        self.snapshot = self.bound
        self.evidence_for = evidence_for
        self.reconciliation_requests: list[str] = []

    async def d0_canary_control_schema_status(self):
        return {"ready": True}

    async def engineering_demo_canary_schema_status(self):
        return {"ready": True}

    async def latest_snapshot(self, executor_id):
        return self.newer  # a heartbeat advanced past S; issuance must not use this

    async def snapshot_by_id(self, executor_id, snapshot_id):
        assert executor_id == EXECUTOR_ID
        return {"snapshot-S": self.bound, "snapshot-S1": self.newer}.get(snapshot_id)

    async def load_engineering_reconciliation(self, snapshot):
        self.reconciliation_requests.append(snapshot.snapshot_id)
        if snapshot.snapshot_id != self.evidence_for:
            raise ReconciliationEvidenceError("RECONCILIATION_EVIDENCE_MISSING_OR_REVOKED")
        identity = fixture_identity(snapshot)
        return identity, fixture_attestation(identity)

    async def enqueue_frozen_engineering_demo_canary_command(
        self, command, *, authority_packet, authority_packet_sha256
    ):
        self.enqueued.append(command)
        return IssuanceDisposition.CREATED


def _frozen(expected_snapshot_id: str):
    values = _packet_values()
    now = datetime.now(UTC)
    values.update(
        executor_id=EXECUTOR_ID,
        expected_account_snapshot_id=expected_snapshot_id,
        account_reference=_snapshot().account_id,
        approved_at_utc=now - timedelta(seconds=2),
        issued_at_utc=now - timedelta(seconds=1),
        expires_at_utc=now + timedelta(seconds=89),
    )
    values["command_content_sha256"] = command_content_sha256_from_fields(values)
    packet = DemoCanaryAuthorityPacketV1.model_validate(values)
    digest = packet_sha256(packet)
    return packet, digest, ProcessLocalIssuanceCapability(packet_sha256_value=digest, command_id=packet.command_id)


@pytest.mark.asyncio
async def test_issuance_uses_frozen_snapshot_even_after_newer_heartbeat():
    repository = ExactSnapshotRepository()
    packet, digest, capability = _frozen("snapshot-S")
    manifest = await EngineeringDemoCanaryAuthorityV1(repository).issue_frozen(  # type: ignore[arg-type]
        packet, expected_packet_sha256=digest, capability=capability
    )
    assert manifest["disposition"] == "CREATED"
    assert repository.reconciliation_requests == ["snapshot-S"]
    guards = repository.enqueued[0].guards
    assert isinstance(guards, EngineeringDemoCanaryGuards)
    assert guards.account_snapshot_id == "snapshot-S"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "expected", "match"),
    [
        ({}, "snapshot-UNKNOWN", "missing or stale"),
        ({"bound_age_seconds": 120}, "snapshot-S", "missing or stale"),
        ({"evidence_for": None}, "snapshot-S", "RECONCILIATION_"),
        ({"evidence_for": "snapshot-S"}, "snapshot-S1", "RECONCILIATION_"),
    ],
    ids=["frozen_snapshot_missing", "frozen_snapshot_stale", "no_evidence_for_S", "packet_names_S1_evidence_is_S"],
)
async def test_issuance_fails_closed_without_valid_evidence_for_the_frozen_snapshot(kwargs, expected, match):
    repository = ExactSnapshotRepository(**kwargs)
    packet, digest, capability = _frozen(expected)
    with pytest.raises(EngineeringDemoCanaryError, match=match):
        await EngineeringDemoCanaryAuthorityV1(repository).issue_frozen(  # type: ignore[arg-type]
            packet, expected_packet_sha256=digest, capability=capability
        )
    assert repository.enqueued == []
    assert not capability.consumed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "newer",
    [
        {"trade_allowed": False},
        {"autotrading_enabled": False},
        {"account_id": "other-account"},
    ],
    ids=["latest_trade_disabled", "latest_autotrading_disabled", "latest_account_differs"],
)
async def test_newer_account_state_vetoes_issuance_from_pinned_snapshot(newer):
    """Codex P1 on #483: S is reconciliation lineage only; a newer snapshot may still veto."""
    repository = ExactSnapshotRepository(newer=newer)
    packet, digest, capability = _frozen("snapshot-S")
    with pytest.raises(EngineeringDemoCanaryError, match="latest"):
        await EngineeringDemoCanaryAuthorityV1(repository).issue_frozen(  # type: ignore[arg-type]
            packet, expected_packet_sha256=digest, capability=capability
        )
    assert repository.enqueued == []
    assert not capability.consumed


def test_latest_state_veto_covers_positions_orders_and_symbol_capability():
    from execution.mt5_command_repository import engineering_canary_latest_state_veto

    pinned = _snapshot(snapshot_id="snapshot-S")
    symbol = pinned.symbols[0]
    kwargs = {"canonical_symbol": symbol.canonical_symbol, "broker_symbol": symbol.broker_symbol}
    same = _snapshot(snapshot_id="snapshot-S1")
    assert engineering_canary_latest_state_veto(same, pinned, **kwargs) is None
    assert engineering_canary_latest_state_veto(pinned, pinned, **kwargs) is None
    assert "missing" in (engineering_canary_latest_state_veto(None, pinned, **kwargs) or "")
    changed = same.model_copy(update={"symbols": [symbol.model_copy(update={"volume_min": symbol.volume_min * 2})]})
    assert "capability" in (engineering_canary_latest_state_veto(changed, pinned, **kwargs) or "")
    busy = same.model_copy(update={"pending_orders": [object()]})
    assert "not flat" in (engineering_canary_latest_state_veto(busy, pinned, **kwargs) or "")
    open_position = same.model_copy(update={"open_positions": [object()]})
    assert "not flat" in (engineering_canary_latest_state_veto(open_position, pinned, **kwargs) or "")
