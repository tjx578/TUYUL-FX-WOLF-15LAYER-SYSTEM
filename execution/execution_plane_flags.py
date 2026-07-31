"""Fail-closed rollout flags for the execution plane.

Every switch that can reach a broker lives here, in one place, with one
parser. The previous arrangement let each call site interpret the environment
for itself, and one of them defaulted ``EXECUTION_ENABLED`` to ``"1"``: a
service started with the variable simply absent would send orders.

Two rules govern this module:

1. **Absent means off.** A flag that is not set is ``False``. Enabling
   execution must be a deliberate act, never the consequence of a missing
   deploy variable.

2. **Unrecognised means off.** The old check asked whether the value was in a
   deny-list, so ``EXECUTION_ENABLED=flase`` -- or ``disabled``, or ``no!`` --
   read as enabled. Only an explicit affirmative enables anything; anything
   else is refused, and refused loudly.

There are two execution planes and they are mutually exclusive: the legacy
Redis-queue push path, and the signed-command bridge. Running both at once
would let one decision reach a broker twice, so the combination is rejected at
startup rather than left to discipline.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from loguru import logger

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})

# --- flag names -------------------------------------------------------------

EXECUTION_ENABLED = "EXECUTION_ENABLED"
LEGACY_PUSH_EXECUTION_ENABLED = "LEGACY_PUSH_EXECUTION_ENABLED"
SIGNED_COMMAND_BRIDGE_ENABLED = "SIGNED_COMMAND_BRIDGE_ENABLED"
EXECUTION_COMMAND_PRODUCER_ENABLED = "EXECUTION_COMMAND_PRODUCER_ENABLED"
RISK_RESERVATION_ENABLED = "RISK_RESERVATION_ENABLED"
TRADE_OUTBOX_WRITE_ENABLED = "TRADE_OUTBOX_WRITE_ENABLED"
EA_COMMAND_DELIVERY_ENABLED = "EA_COMMAND_DELIVERY_ENABLED"
MT5_ORDER_SEND_ENABLED = "MT5_ORDER_SEND_ENABLED"
EA_BRIDGE_URL = "EA_BRIDGE_URL"

#: Every flag that can move the system closer to a broker order.
EXECUTION_PLANE_FLAGS: tuple[str, ...] = (
    EXECUTION_ENABLED,
    LEGACY_PUSH_EXECUTION_ENABLED,
    SIGNED_COMMAND_BRIDGE_ENABLED,
    EXECUTION_COMMAND_PRODUCER_ENABLED,
    RISK_RESERVATION_ENABLED,
    TRADE_OUTBOX_WRITE_ENABLED,
    EA_COMMAND_DELIVERY_ENABLED,
    MT5_ORDER_SEND_ENABLED,
)


class ExecutionPlaneConfigError(RuntimeError):
    """Raised when the execution-plane configuration is unsafe or unreadable."""


def parse_execution_flag(
    name: str,
    raw: str | None,
    *,
    strict: bool = False,
) -> bool:
    """Resolve one execution flag, failing closed.

    ``strict`` raises on an unrecognised value instead of returning ``False``.
    Preflight uses strict mode so a typo stops the deploy; runtime uses lenient
    mode so a typo suppresses execution rather than crashing a live worker --
    in both directions the unsafe outcome is unreachable.
    """
    if raw is None:
        return False
    value = str(raw).strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    message = (
        f"{name} has an unrecognised value {raw!r}; expected one of {sorted(TRUE_VALUES)} or {sorted(FALSE_VALUES)}"
    )
    if strict:
        raise ExecutionPlaneConfigError(f"EXECUTION_FLAG_INVALID:{name}")
    # Never guess in favour of execution.
    logger.warning("{} — treating as disabled", message)
    return False


def execution_flag(name: str, environ: Mapping[str, str] | None = None, *, strict: bool = False) -> bool:
    source = os.environ if environ is None else environ
    return parse_execution_flag(name, source.get(name), strict=strict)


@dataclass(frozen=True)
class ExecutionPlaneFlags:
    """Resolved snapshot of every execution-plane switch."""

    execution_enabled: bool = False
    legacy_push_execution_enabled: bool = False
    signed_command_bridge_enabled: bool = False
    execution_command_producer_enabled: bool = False
    risk_reservation_enabled: bool = False
    trade_outbox_write_enabled: bool = False
    ea_command_delivery_enabled: bool = False
    mt5_order_send_enabled: bool = False
    ea_bridge_url: str | None = None

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        strict: bool = False,
    ) -> ExecutionPlaneFlags:
        source = os.environ if environ is None else environ

        def _flag(name: str) -> bool:
            return parse_execution_flag(name, source.get(name), strict=strict)

        raw_url = source.get(EA_BRIDGE_URL)
        url = str(raw_url).strip() if raw_url is not None else None
        return cls(
            execution_enabled=_flag(EXECUTION_ENABLED),
            legacy_push_execution_enabled=_flag(LEGACY_PUSH_EXECUTION_ENABLED),
            signed_command_bridge_enabled=_flag(SIGNED_COMMAND_BRIDGE_ENABLED),
            execution_command_producer_enabled=_flag(EXECUTION_COMMAND_PRODUCER_ENABLED),
            risk_reservation_enabled=_flag(RISK_RESERVATION_ENABLED),
            trade_outbox_write_enabled=_flag(TRADE_OUTBOX_WRITE_ENABLED),
            ea_command_delivery_enabled=_flag(EA_COMMAND_DELIVERY_ENABLED),
            mt5_order_send_enabled=_flag(MT5_ORDER_SEND_ENABLED),
            ea_bridge_url=url or None,
        )

    @property
    def any_execution_reachable(self) -> bool:
        """True when any switch could move a decision toward a broker."""
        return any(
            (
                self.execution_enabled,
                self.legacy_push_execution_enabled,
                self.signed_command_bridge_enabled,
                self.execution_command_producer_enabled,
                self.risk_reservation_enabled,
                self.trade_outbox_write_enabled,
                self.ea_command_delivery_enabled,
                self.mt5_order_send_enabled,
            )
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def validate_execution_plane(flags: ExecutionPlaneFlags) -> None:
    """Refuse configurations that could produce a duplicate broker effect.

    Each rule below exists because the combination is silently dangerous, not
    merely unusual.
    """
    if flags.legacy_push_execution_enabled and flags.signed_command_bridge_enabled:
        # One decision would reach the broker down two independent paths.
        raise ExecutionPlaneConfigError("EXECUTION_PLANE_CONFLICT:legacy_push+signed_command_bridge")

    if flags.legacy_push_execution_enabled and not flags.execution_enabled:
        raise ExecutionPlaneConfigError("EXECUTION_PLANE_INCOHERENT:legacy_push_without_execution_enabled")

    if flags.legacy_push_execution_enabled and not flags.ea_bridge_url:
        # The old implicit http://localhost:8081 default made this reachable by
        # accident; an explicit address is now required.
        raise ExecutionPlaneConfigError("EXECUTION_PLANE_MISSING:EA_BRIDGE_URL")

    if flags.mt5_order_send_enabled and not flags.ea_command_delivery_enabled:
        raise ExecutionPlaneConfigError("EXECUTION_PLANE_INCOHERENT:order_send_without_command_delivery")

    if flags.ea_command_delivery_enabled and not flags.execution_command_producer_enabled:
        raise ExecutionPlaneConfigError("EXECUTION_PLANE_INCOHERENT:command_delivery_without_producer")


def assert_execution_isolated(flags: ExecutionPlaneFlags, *, phase: str) -> None:
    """Refuse to run an observation phase with any execution switch on."""
    if flags.any_execution_reachable:
        enabled = sorted(name for name, value in flags.as_dict().items() if value is True)
        raise ExecutionPlaneConfigError(f"EXECUTION_NOT_ISOLATED:phase={phase}:enabled={','.join(enabled)}")


def log_execution_plane(flags: ExecutionPlaneFlags, *, service: str) -> None:
    """State the resolved plane at startup so it is never inferred from silence."""
    logger.info(
        "[ExecutionPlane] service={} execution_enabled={} legacy_push={} signed_bridge={} "
        "producer={} risk_reservation={} outbox_write={} command_delivery={} order_send={} "
        "ea_bridge_url={}",
        service,
        flags.execution_enabled,
        flags.legacy_push_execution_enabled,
        flags.signed_command_bridge_enabled,
        flags.execution_command_producer_enabled,
        flags.risk_reservation_enabled,
        flags.trade_outbox_write_enabled,
        flags.ea_command_delivery_enabled,
        flags.mt5_order_send_enabled,
        flags.ea_bridge_url or "<unset>",
    )


__all__ = [
    "EA_BRIDGE_URL",
    "EA_COMMAND_DELIVERY_ENABLED",
    "EXECUTION_COMMAND_PRODUCER_ENABLED",
    "EXECUTION_ENABLED",
    "EXECUTION_PLANE_FLAGS",
    "FALSE_VALUES",
    "LEGACY_PUSH_EXECUTION_ENABLED",
    "MT5_ORDER_SEND_ENABLED",
    "RISK_RESERVATION_ENABLED",
    "SIGNED_COMMAND_BRIDGE_ENABLED",
    "TRADE_OUTBOX_WRITE_ENABLED",
    "TRUE_VALUES",
    "ExecutionPlaneConfigError",
    "ExecutionPlaneFlags",
    "assert_execution_isolated",
    "execution_flag",
    "log_execution_plane",
    "parse_execution_flag",
    "validate_execution_plane",
]
