"""Regression tests — compliance auto-mode gate in OrchestratorCoordinator.

Validates:
  1. Paused auto-mode blocks the pipeline BEFORE the firewall runs.
  2. Normal (ENABLED) mode proceeds through to the firewall.

These are boundary-enforcement regressions: the compliance gate must never
be bypassed, and the blocked path must never touch the firewall.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.orchestrator.compliance_auto_mode import (
    AutoTradingState,
    ComplianceAutoMode,
)
from services.orchestrator.coordinator import OrchestratorCoordinator

# ── Minimal fakes ─────────────────────────────────────────────────────────


@dataclass
class _FakeTakeResponse:
    status: str = "PENDING"
    signal_id: str = "sig_reg"
    account_id: str = "acc_reg"


class _FakeTakeService:
    """Records transitions without side-effects."""

    def __init__(self) -> None:
        self.transitions: list[tuple[str, str]] = []

    async def get(self, take_id: str) -> _FakeTakeResponse:
        return _FakeTakeResponse()

    async def transition(self, take_id: str, new_status: str, **kwargs: Any) -> None:
        self.transitions.append((take_id, new_status))


class _FakeFirewall:
    """Tracks whether evaluate() was ever called."""

    def __init__(self) -> None:
        self.called = False

    async def evaluate(
        self, take_id: str, signal: dict[str, Any], account_state: dict[str, Any]
    ) -> _FakeFirewallResult:
        self.called = True
        return _FakeFirewallResult()


@dataclass
class _FakeFirewallResult:
    verdict: str = "APPROVED"
    firewall_id: str = "fw_reg"
    short_circuited_at: str | None = None


class _FakePublisher:
    """Captures emitted events."""

    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    async def publish(
        self,
        stream: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        self.events.append(fields)
        return "fake_id"


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_compliance(state: AutoTradingState) -> ComplianceAutoMode:
    cam = ComplianceAutoMode(redis_client=_FakeRedis(), stream_publisher=_FakePublisher())
    cam._state = state  # noqa: SLF001 — force desired state for test
    return cam


def _build_coordinator(
    *,
    compliance: ComplianceAutoMode | None = None,
    firewall: _FakeFirewall | None = None,
    take_service: _FakeTakeService | None = None,
    publisher: _FakePublisher | None = None,
) -> tuple[OrchestratorCoordinator, _FakeTakeService, _FakeFirewall, _FakePublisher]:
    ts = take_service or _FakeTakeService()
    fw = firewall or _FakeFirewall()
    pub = publisher or _FakePublisher()
    coord = OrchestratorCoordinator(
        take_signal_service=ts,
        risk_firewall=fw,
        stream_publisher=pub,
        compliance_auto_mode=compliance,
    )
    return coord, ts, fw, pub


# ── Regression tests ──────────────────────────────────────────────────────

SIGNAL = {"symbol": "EURUSD", "direction": "BUY"}
ACCOUNT = {"account_id": "acc_reg"}


class TestComplianceGateRegression:
    """Regression: paused gate must block; enabled gate must proceed."""

    async def test_paused_auto_mode_blocks_before_firewall(self) -> None:
        """PAUSED compliance → REJECTED + COMPLIANCE_BLOCKED, firewall never called."""
        compliance = _make_compliance(AutoTradingState.PAUSED)
        coord, take_svc, firewall, publisher = _build_coordinator(compliance=compliance)

        result = await coord.process_take_signal("take_r1", SIGNAL, ACCOUNT)

        # Blocked result
        assert result.status == "COMPLIANCE_BLOCKED"
        assert result.verdict == "REJECTED"
        assert "paused" in result.reason.lower()

        # Firewall must NOT have been invoked
        assert not firewall.called, "Firewall must not run when compliance gate blocks"

        # Take-signal transitioned to REJECTED
        assert ("take_r1", "REJECTED") in take_svc.transitions

        # Compliance-blocked event emitted
        blocked = [e for e in publisher.events if e.get("event_type") == "ORCHESTRATION_BLOCKED_BY_COMPLIANCE"]
        assert len(blocked) == 1
        assert blocked[0]["take_id"] == "take_r1"

    async def test_enabled_auto_mode_proceeds_to_firewall(self) -> None:
        """ENABLED compliance → pipeline reaches the firewall normally."""
        compliance = _make_compliance(AutoTradingState.ENABLED)
        coord, _ts, firewall, _pub = _build_coordinator(compliance=compliance)

        result = await coord.process_take_signal("take_r2", SIGNAL, ACCOUNT)

        # Firewall MUST have been called
        assert firewall.called, "Firewall must be called when compliance gate passes"

        # Not blocked
        assert result.status != "COMPLIANCE_BLOCKED"
        assert result.verdict != "REJECTED" or result.status != "COMPLIANCE_BLOCKED"
