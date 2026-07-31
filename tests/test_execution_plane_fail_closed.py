"""The execution plane must be unreachable unless someone deliberately opened it.

These map one-to-one onto the agreed acceptance criteria:

    env missing                    -> execution OFF
    invalid boolean                -> execution OFF, or startup rejected
    legacy worker disabled         -> execution:queue not consumed
    both execution planes enabled  -> startup fails
    broker HTTP call               -> 0

The regression being guarded is specific: ``EXECUTION_ENABLED`` used to default
to ``"1"`` and was checked against a deny-list, so an absent variable -- or a
typo like ``flase`` -- meant orders would be sent.
"""

from __future__ import annotations

import asyncio

import pytest

from execution.execution_plane_flags import (
    EXECUTION_ENABLED,
    EXECUTION_PLANE_FLAGS,
    ExecutionPlaneConfigError,
    ExecutionPlaneFlags,
    assert_execution_isolated,
    parse_execution_flag,
    validate_execution_plane,
)
from services.trade.preflight import (
    LEGACY_PUSH_PHASE,
    OBSERVE_PHASE,
    SIGNED_COMMAND_PHASE,
    resolve_expected_phase,
    run_preflight,
    validate_trade_phase,
)


@pytest.fixture(autouse=True)
def _clear_execution_env(monkeypatch):
    for name in (*EXECUTION_PLANE_FLAGS, "EA_BRIDGE_URL", "TRADE_EXPECTED_PHASE"):
        monkeypatch.delenv(name, raising=False)


def _flags(**overrides) -> ExecutionPlaneFlags:
    return ExecutionPlaneFlags(**overrides)


# --------------------------------------------------------------------------
# absent means off
# --------------------------------------------------------------------------


def test_absent_env_disables_execution():
    """The exact regression: a missing variable used to mean enabled."""
    assert parse_execution_flag(EXECUTION_ENABLED, None) is False


def test_every_execution_flag_defaults_off():
    flags = ExecutionPlaneFlags.from_env({})

    assert flags.any_execution_reachable is False
    assert all(value is False for name, value in flags.as_dict().items() if name != "ea_bridge_url")


def test_broker_executor_is_disabled_without_env(monkeypatch):
    from execution.broker_executor import BrokerExecutor

    monkeypatch.delenv(EXECUTION_ENABLED, raising=False)

    assert BrokerExecutor._execution_enabled() is False


# --------------------------------------------------------------------------
# unrecognised means off, never "probably yes"
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["flase", "disabled", "no!", "maybe", "TRUE_", "2", "-1"])
def test_unrecognised_values_disable_execution(value):
    assert parse_execution_flag(EXECUTION_ENABLED, value) is False


@pytest.mark.parametrize("value", ["flase", "disabled", "maybe"])
def test_unrecognised_values_are_rejected_in_strict_mode(value):
    with pytest.raises(ExecutionPlaneConfigError, match="EXECUTION_FLAG_INVALID"):
        parse_execution_flag(EXECUTION_ENABLED, value, strict=True)


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_only_explicit_affirmatives_enable(value):
    assert parse_execution_flag(EXECUTION_ENABLED, value) is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_explicit_negatives_disable(value):
    assert parse_execution_flag(EXECUTION_ENABLED, value) is False


def test_broker_executor_typo_does_not_enable_execution(monkeypatch):
    from execution.broker_executor import BrokerExecutor

    monkeypatch.setenv(EXECUTION_ENABLED, "flase")

    assert BrokerExecutor._execution_enabled() is False


# --------------------------------------------------------------------------
# the two planes are mutually exclusive
# --------------------------------------------------------------------------


def test_both_execution_planes_enabled_is_rejected():
    """One decision must not be able to reach a broker twice."""
    with pytest.raises(ExecutionPlaneConfigError, match="EXECUTION_PLANE_CONFLICT"):
        validate_execution_plane(
            _flags(
                execution_enabled=True,
                legacy_push_execution_enabled=True,
                signed_command_bridge_enabled=True,
                ea_bridge_url="http://bridge.internal",
            )
        )


def test_legacy_push_without_execution_enabled_is_incoherent():
    with pytest.raises(ExecutionPlaneConfigError, match="legacy_push_without_execution_enabled"):
        validate_execution_plane(_flags(legacy_push_execution_enabled=True, ea_bridge_url="http://bridge.internal"))


def test_legacy_push_requires_an_explicit_bridge_url():
    """The old implicit http://localhost:8081 made this reachable by accident."""
    with pytest.raises(ExecutionPlaneConfigError, match="EA_BRIDGE_URL"):
        validate_execution_plane(_flags(execution_enabled=True, legacy_push_execution_enabled=True))


def test_order_send_requires_command_delivery():
    with pytest.raises(ExecutionPlaneConfigError, match="order_send_without_command_delivery"):
        validate_execution_plane(_flags(mt5_order_send_enabled=True))


def test_command_delivery_requires_a_producer():
    with pytest.raises(ExecutionPlaneConfigError, match="command_delivery_without_producer"):
        validate_execution_plane(_flags(ea_command_delivery_enabled=True))


def test_a_coherent_legacy_push_plane_is_accepted():
    validate_execution_plane(
        _flags(
            execution_enabled=True,
            legacy_push_execution_enabled=True,
            ea_bridge_url="http://bridge.internal",
        )
    )


# --------------------------------------------------------------------------
# observation phases must be isolated
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flag",
    [
        "execution_enabled",
        "legacy_push_execution_enabled",
        "signed_command_bridge_enabled",
        "execution_command_producer_enabled",
        "risk_reservation_enabled",
        "trade_outbox_write_enabled",
        "ea_command_delivery_enabled",
        "mt5_order_send_enabled",
    ],
)
def test_any_single_switch_breaks_isolation(flag):
    with pytest.raises(ExecutionPlaneConfigError, match="EXECUTION_NOT_ISOLATED"):
        assert_execution_isolated(_flags(**{flag: True}), phase="production-observe")


def test_isolation_holds_when_everything_is_off():
    assert_execution_isolated(_flags(), phase="production-observe")


# --------------------------------------------------------------------------
# trade preflight
# --------------------------------------------------------------------------


def test_observe_is_the_default_phase():
    assert resolve_expected_phase({}) == OBSERVE_PHASE


def test_unknown_phase_is_rejected():
    with pytest.raises(ExecutionPlaneConfigError, match="TRADE_EXPECTED_PHASE_INVALID"):
        resolve_expected_phase({"TRADE_EXPECTED_PHASE": "yolo"})


def test_observe_phase_refuses_any_execution_switch():
    with pytest.raises(ExecutionPlaneConfigError, match="EXECUTION_NOT_ISOLATED"):
        validate_trade_phase(_flags(risk_reservation_enabled=True), OBSERVE_PHASE)


def test_legacy_push_phase_requires_the_legacy_flag():
    with pytest.raises(ExecutionPlaneConfigError, match="legacy-push_requires"):
        validate_trade_phase(_flags(), LEGACY_PUSH_PHASE)


def test_signed_command_phase_rejects_legacy_push():
    with pytest.raises(ExecutionPlaneConfigError, match="EXECUTION_PLANE_CONFLICT"):
        validate_trade_phase(
            _flags(
                execution_enabled=True,
                legacy_push_execution_enabled=True,
                signed_command_bridge_enabled=True,
                ea_bridge_url="http://bridge.internal",
            ),
            SIGNED_COMMAND_PHASE,
        )


def test_preflight_reports_an_isolated_observe_deployment():
    report = asyncio.run(run_preflight({}))

    assert report["ready"] is True
    assert report["expected_phase"] == OBSERVE_PHASE
    assert report["execution_isolated"] is True
    assert report["legacy_push_worker_will_start"] is False


def test_preflight_rejects_a_typo_rather_than_reading_it_as_off():
    """Lenient parsing would hide the operator's real intent at deploy time."""
    with pytest.raises(ExecutionPlaneConfigError, match="EXECUTION_FLAG_INVALID"):
        asyncio.run(run_preflight({EXECUTION_ENABLED: "flase"}))


# --------------------------------------------------------------------------
# the legacy queue must have no consumer when disabled
# --------------------------------------------------------------------------


def test_worker_construction_is_refused_when_legacy_push_is_off(monkeypatch):
    from execution.async_worker import AsyncExecutionWorker

    monkeypatch.delenv("LEGACY_PUSH_EXECUTION_ENABLED", raising=False)

    with pytest.raises(ExecutionPlaneConfigError, match="LEGACY_PUSH_EXECUTION_DISABLED"):
        AsyncExecutionWorker()


def test_worker_entrypoint_returns_without_consuming_the_queue(monkeypatch):
    """_main must exit quietly, not crash: a disabled plane is a valid state."""
    import execution.async_worker as worker_module

    monkeypatch.delenv("LEGACY_PUSH_EXECUTION_ENABLED", raising=False)

    def _fail(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("execution:queue must not be consumed while disabled")

    monkeypatch.setattr(worker_module, "AsyncExecutionWorker", _fail)
    monkeypatch.setattr(worker_module, "start_http_server", _fail)

    asyncio.run(worker_module._main())


# --------------------------------------------------------------------------
# no broker traffic
# --------------------------------------------------------------------------


def test_disabled_executor_makes_no_http_call(monkeypatch):
    import httpx

    from execution.broker_executor import BrokerExecutor, ExecutionRequest, OrderAction

    monkeypatch.delenv(EXECUTION_ENABLED, raising=False)

    def _fail(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("broker HTTP call attempted while execution disabled")

    monkeypatch.setattr(httpx, "post", _fail)

    executor = BrokerExecutor(ea_url="http://bridge.internal")
    result = executor.execute(
        ExecutionRequest(
            action=OrderAction.PLACE,
            account_id="acct-1",
            symbol="EURUSD",
            lot_size=0.01,
            order_type="BUY",
        )
    )

    assert result.success is False
    assert result.error_msg == "execution_disabled"
    assert result.raw is not None and result.raw["sent"] is False


def test_enabled_executor_without_a_url_refuses_rather_than_guessing(monkeypatch):
    """Removing the localhost default must not become a silent fallback."""
    import httpx

    from execution.broker_executor import BrokerExecutor, ExecutionRequest, OrderAction

    monkeypatch.setenv(EXECUTION_ENABLED, "true")
    monkeypatch.delenv("EA_BRIDGE_URL", raising=False)

    def _fail(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("broker HTTP call attempted without a configured bridge")

    monkeypatch.setattr(httpx, "post", _fail)

    result = BrokerExecutor().execute(
        ExecutionRequest(
            action=OrderAction.PLACE,
            account_id="acct-1",
            symbol="EURUSD",
            lot_size=0.01,
            order_type="BUY",
        )
    )

    assert result.success is False
    assert result.error_msg == "ea_bridge_url_not_configured"


def test_unconfigured_executor_has_no_implicit_localhost(monkeypatch):
    from execution.broker_executor import BrokerExecutor

    monkeypatch.delenv("EA_BRIDGE_URL", raising=False)

    assert BrokerExecutor().runtime_snapshot()["ea_url"] == ""


def test_runtime_snapshot_reports_suppression(monkeypatch):
    from execution.broker_executor import BrokerExecutor

    monkeypatch.delenv(EXECUTION_ENABLED, raising=False)
    snapshot = BrokerExecutor(ea_url="http://bridge.internal").runtime_snapshot()

    assert snapshot["execution_enabled"] is False
    assert snapshot["broker_calls_suppressed"] is True
