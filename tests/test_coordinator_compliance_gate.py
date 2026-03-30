"""Tests for P1 compliance gate in OrchestratorCoordinator.

Validates that the compliance auto-mode enforcement is called BEFORE
the risk firewall in the coordinator pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from services.orchestrator.compliance_auto_mode import (
    AutoTradingState,
    ComplianceAutoMode,
)
from services.orchestrator.coordinator import (
    OrchestratorCoordinator,
)

# ── Minimal fakes ─────────────────────────────────────────────────────


@dataclass
class FakeTakeResponse:
    status: str = "PENDING"
    signal_id: str = "sig_001"
    account_id: str = "acc_001"


class FakeTakeSignalService:
    def __init__(self, response: FakeTakeResponse | None = None) -> None:
        self._response = response or FakeTakeResponse()
        self.transitions: list[tuple[str, str]] = []

    async def get(self, take_id: str) -> FakeTakeResponse | None:
        return self._response

    async def transition(self, take_id: str, new_status: str, **kwargs: Any) -> None:
        self.transitions.append((take_id, new_status))


@dataclass
class FakeFirewallResult:
    verdict: str = "APPROVED"
    firewall_id: str = "fw_001"
    short_circuited_at: str | None = None


class FakeRiskFirewall:
    def __init__(self, result: FakeFirewallResult | None = None) -> None:
        self._result = result or FakeFirewallResult()
        self.called = False

    async def evaluate(self, take_id: str, signal: dict, account_state: dict) -> FakeFirewallResult:
        self.called = True
        return self._result


class FakeStreamPublisher:
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


class FakeRedisForAutoMode:
    """Minimal Redis stub for ComplianceAutoMode persistence."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value


# ── Tests ─────────────────────────────────────────────────────────────


class TestComplianceGateBeforeFirewall:
    """P1: compliance auto-mode gate must block BEFORE firewall runs."""

    @pytest.fixture()
    def publisher(self) -> FakeStreamPublisher:
        return FakeStreamPublisher()

    @pytest.fixture()
    def take_service(self) -> FakeTakeSignalService:
        return FakeTakeSignalService()

    @pytest.fixture()
    def firewall(self) -> FakeRiskFirewall:
        return FakeRiskFirewall()

    def _make_compliance(self, state: AutoTradingState = AutoTradingState.ENABLED) -> ComplianceAutoMode:
        redis = FakeRedisForAutoMode()
        cam = ComplianceAutoMode(redis_client=redis, stream_publisher=FakeStreamPublisher())
        # Force the desired state
        cam._state = state
        return cam

    def _make_coordinator(
        self,
        take_service: FakeTakeSignalService,
        firewall: FakeRiskFirewall,
        publisher: FakeStreamPublisher,
        compliance: ComplianceAutoMode | None = None,
    ) -> OrchestratorCoordinator:
        return OrchestratorCoordinator(
            take_signal_service=take_service,
            risk_firewall=firewall,
            stream_publisher=publisher,
            compliance_auto_mode=compliance,
        )

    @pytest.mark.asyncio()
    async def test_compliance_paused_blocks_before_firewall(
        self,
        take_service: FakeTakeSignalService,
        firewall: FakeRiskFirewall,
        publisher: FakeStreamPublisher,
    ) -> None:
        """When compliance is PAUSED, the coordinator must reject immediately
        and the firewall must NOT be called."""
        compliance = self._make_compliance(AutoTradingState.PAUSED)
        coord = self._make_coordinator(take_service, firewall, publisher, compliance)

        result = await coord.process_take_signal(
            take_id="take_001",
            signal={"symbol": "EURUSD", "direction": "BUY"},
            account_state={"account_id": "acc_001"},
        )

        assert result.status == "COMPLIANCE_BLOCKED"
        assert result.verdict == "REJECTED"
        assert "paused" in result.reason.lower()
        assert not firewall.called, "Firewall must NOT be called when compliance blocks"

        # P1 upgrade: take-signal must be transitioned to REJECTED
        assert ("take_001", "REJECTED") in take_service.transitions

        # P1 upgrade: ORCHESTRATION_BLOCKED_BY_COMPLIANCE event must be emitted
        blocked_events = [e for e in publisher.events if e.get("event_type") == "ORCHESTRATION_BLOCKED_BY_COMPLIANCE"]
        assert len(blocked_events) == 1
        assert blocked_events[0]["take_id"] == "take_001"

    @pytest.mark.asyncio()
    async def test_compliance_enabled_allows_firewall(
        self,
        take_service: FakeTakeSignalService,
        firewall: FakeRiskFirewall,
        publisher: FakeStreamPublisher,
    ) -> None:
        """When compliance is ENABLED, the pipeline should proceed to the firewall."""
        compliance = self._make_compliance(AutoTradingState.ENABLED)
        coord = self._make_coordinator(take_service, firewall, publisher, compliance)

        result = await coord.process_take_signal(
            take_id="take_002",
            signal={"symbol": "EURUSD", "direction": "BUY"},
            account_state={"account_id": "acc_001"},
        )

        assert firewall.called, "Firewall must be called when compliance is enabled"
        assert result.status != "COMPLIANCE_BLOCKED"

    @pytest.mark.asyncio()
    async def test_no_compliance_injected_skips_gate(
        self,
        take_service: FakeTakeSignalService,
        firewall: FakeRiskFirewall,
        publisher: FakeStreamPublisher,
    ) -> None:
        """When no ComplianceAutoMode is injected, the gate is a no-op
        and the pipeline proceeds normally (backward compatible)."""
        coord = self._make_coordinator(take_service, firewall, publisher, compliance=None)

        result = await coord.process_take_signal(
            take_id="take_003",
            signal={"symbol": "EURUSD", "direction": "BUY"},
            account_state={"account_id": "acc_001"},
        )

        assert firewall.called
        assert result.status != "COMPLIANCE_BLOCKED"

    @pytest.mark.asyncio()
    async def test_compliance_gate_order_is_before_firewall(
        self,
        take_service: FakeTakeSignalService,
        publisher: FakeStreamPublisher,
    ) -> None:
        """Prove ordering: when compliance is PAUSED, firewall.evaluate is never reached."""
        call_order: list[str] = []

        class TrackingFirewall:
            async def evaluate(self, take_id: str, signal: dict, account_state: dict) -> FakeFirewallResult:
                call_order.append("firewall")
                return FakeFirewallResult()

        compliance = self._make_compliance(AutoTradingState.PAUSED)
        coord = OrchestratorCoordinator(
            take_signal_service=take_service,
            risk_firewall=TrackingFirewall(),
            stream_publisher=publisher,
            compliance_auto_mode=compliance,
        )

        result = await coord.process_take_signal(
            take_id="take_004",
            signal={"symbol": "EURUSD"},
            account_state={"account_id": "acc_001"},
        )

        assert result.status == "COMPLIANCE_BLOCKED"
        assert "firewall" not in call_order, "Firewall must not run when compliance is paused"
        # Transition and event must still fire even in ordering proof
        assert ("take_004", "REJECTED") in take_service.transitions
