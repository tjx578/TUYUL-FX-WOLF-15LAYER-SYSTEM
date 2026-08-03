"""Unit gates for the default-off MT5 risk command producer."""

from __future__ import annotations

import pytest

from execution.execution_plane_flags import ExecutionPlaneFlags
from execution.mt5_risk_command_producer import (
    MT5RiskCommandProducer,
    RiskCommandProducerNotReadyError,
    RiskCommandProductionPolicy,
)


class _AvailablePostgres:
    is_available = True


def _enabled_flags(
    *,
    execution_enabled: bool = True,
    signed_command_bridge_enabled: bool = True,
    execution_command_producer_enabled: bool = True,
    risk_reservation_enabled: bool = True,
    trade_outbox_write_enabled: bool = True,
    ea_command_delivery_enabled: bool = False,
    mt5_order_send_enabled: bool = False,
) -> ExecutionPlaneFlags:
    return ExecutionPlaneFlags(
        execution_enabled=execution_enabled,
        signed_command_bridge_enabled=signed_command_bridge_enabled,
        execution_command_producer_enabled=execution_command_producer_enabled,
        risk_reservation_enabled=risk_reservation_enabled,
        trade_outbox_write_enabled=trade_outbox_write_enabled,
        ea_command_delivery_enabled=ea_command_delivery_enabled,
        mt5_order_send_enabled=mt5_order_send_enabled,
    )


def _producer(*, flags: ExecutionPlaneFlags) -> MT5RiskCommandProducer:
    return MT5RiskCommandProducer(
        pg=_AvailablePostgres(),  # type: ignore[arg-type]
        flags=flags,
        environ={
            "EXECUTOR_COMMAND_SIGNING_SECRET": "s" * 32,
            "EXECUTOR_COMMAND_SIGNING_KEY_ID": "unit-key-v1",
        },
    )


def test_producer_is_dark_when_flags_are_absent() -> None:
    producer = _producer(flags=ExecutionPlaneFlags())
    with pytest.raises(RiskCommandProducerNotReadyError, match="COMMAND_PRODUCER_DISABLED"):
        producer._require_ready()


@pytest.mark.parametrize(
    "flag",
    [
        "execution_enabled",
        "signed_command_bridge_enabled",
        "execution_command_producer_enabled",
        "risk_reservation_enabled",
        "trade_outbox_write_enabled",
    ],
)
def test_each_producer_prerequisite_fails_closed(flag: str) -> None:
    producer = _producer(flags=_enabled_flags(**{flag: False}))
    with pytest.raises(RiskCommandProducerNotReadyError, match="COMMAND_PRODUCER_DISABLED"):
        producer._require_ready()


def test_producer_refuses_order_send_even_when_other_flags_are_enabled() -> None:
    producer = _producer(
        flags=_enabled_flags(
            ea_command_delivery_enabled=True,
            mt5_order_send_enabled=True,
        )
    )
    with pytest.raises(RiskCommandProducerNotReadyError, match="ORDER_SEND_DISABLED"):
        producer._require_ready()


def test_producer_requires_signing_material() -> None:
    producer = MT5RiskCommandProducer(
        pg=_AvailablePostgres(),  # type: ignore[arg-type]
        flags=_enabled_flags(),
        environ={},
    )
    with pytest.raises(RiskCommandProducerNotReadyError, match="SIGNING_SECRET"):
        producer._require_ready()


def test_production_policy_rejects_an_unusable_command_window() -> None:
    with pytest.raises(ValueError, match="minimum command window"):
        RiskCommandProductionPolicy(command_ttl_seconds=5, minimum_command_window_seconds=5)
