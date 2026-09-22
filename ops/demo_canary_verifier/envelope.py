"""Frozen DEMO-canary envelope and its pre-submit evidence checker.

The envelope is an explicit, versioned, hash-pinned config. Every field is a
``Literal`` so no other value can even be parsed, and the canonical digest of the
shipped file must equal :data:`ENVELOPE_V1_SHA256`. The checker validates an
exported pre-submit evidence bundle and REFUSES anything outside the envelope.
It never repairs, normalizes, retries, or issues a command, and its decision is
never submit authority by itself (``SUBMIT_AUTHORITY`` is always ``False``).

Reused contracts (not redefined here):
- ``contracts.mt5_execution_protocol``: ``ExecutionCommandV1`` (command identity,
  ``idempotency_key``, guards, executor binding) and ``AccountSnapshotV1``.
- ``execution.mt5_command_repository.engineering_canary_latest_state_veto``: the
  canonical latest-state veto (PR #483 lineage), re-evaluated, never re-implemented.
- ``ENGINEERING_DEMO_CANARY_EA_VERSION``: the DEMO EA that runs the final
  OrderCheck preflight immediately before its single ``OrderSend``.
- ``ops.mt5_mcp.report_integrity.evidence_digest``: canonical evidence hashing.
- MT5 ``mt5_account_get`` record shape from ``ops.mt5_mcp.server`` (``trade_mode``
  0 is ``ACCOUNT_TRADE_MODE_DEMO``, as enforced in
  ``execution.broker_reconciliation_evidence``).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from contracts.mt5_execution_protocol import (
    ENGINEERING_DEMO_CANARY_EA_VERSION,
    AccountSnapshotV1,
    CommandGuards,
    CommandSource,
    EngineeringDemoCanaryGuards,
    ExecutionAction,
    ExecutionCommandV1,
    ExecutorMode,
    ShadowAcceptanceSource,
)
from ops.mt5_mcp.report_integrity import evidence_digest

ENVELOPE_SCHEMA: Final = "wolf15.demo-canary.envelope.v1"
PRESUBMIT_BUNDLE_SCHEMA: Final = "wolf15.demo-canary.presubmit-bundle.v1"
ENVELOPE_DECISION_SCHEMA: Final = "wolf15.demo-canary.envelope-decision.v1"
ENVELOPE_V1_PATH: Final = Path(__file__).with_name("envelope_v1.json")
# Canonical digest of envelope_v1.json (evidence_digest of the parsed model).
# Changing any envelope value requires a new versioned file and a new pin.
ENVELOPE_V1_SHA256: Final = "sha256:3bd8f246c136f3be6ff9dc62c2396600bd1447ce62c8da7915262004136beacb"
MT5_ACCOUNT_TRADE_MODE_DEMO: Final = 0
ENTRY_ACTIONS: Final = frozenset({ExecutionAction.PLACE_MARKET, ExecutionAction.PLACE_PENDING})

LatestStateVeto = Callable[..., "str | None"]


class EnvelopeError(ValueError):
    """The envelope config itself is not the frozen, pinned envelope."""


class CanaryEnvelopeV1(BaseModel):
    """The only envelope this checker accepts. Field names are the owner's spelling."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["wolf15.demo-canary.envelope.v1"]
    ACCOUNT: Literal["DEMO"]
    MAX_SUBMIT: Literal[1]
    AUTO_RETRY: Literal[False]
    PYRAMIDING: Literal[False]
    MULTIPLE_POSITION: Literal[False]
    FLAT_STATE_REQUIRED: Literal[True]
    LATEST_STATE_VETO: Literal["REQUIRED"]
    EA_FINAL_PREFLIGHT: Literal["REQUIRED"]


def envelope_sha256(envelope: CanaryEnvelopeV1) -> str:
    return evidence_digest(envelope.model_dump(mode="json"))


def load_envelope(path: Path = ENVELOPE_V1_PATH, *, expected_sha256: str = ENVELOPE_V1_SHA256) -> CanaryEnvelopeV1:
    """Parse the envelope file and refuse it unless its canonical digest is the pinned one."""

    try:
        envelope = CanaryEnvelopeV1.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise EnvelopeError("ENVELOPE_INVALID") from exc
    if envelope_sha256(envelope) != expected_sha256:
        raise EnvelopeError("ENVELOPE_SHA256_MISMATCH")
    return envelope


def _canonical_latest_state_veto() -> LatestStateVeto:
    # Lazy import: the repository module defines (but never opens) a PostgreSQL
    # client. Importing it here reuses the exact veto predicate without any I/O.
    from execution.mt5_command_repository import engineering_canary_latest_state_veto  # noqa: PLC0415

    return engineering_canary_latest_state_veto


def _parse_commands(raw: Any, refusals: set[str]) -> list[ExecutionCommandV1]:
    if raw is None:
        refusals.add("COMMAND_EVIDENCE_MISSING")
        return []
    if not isinstance(raw, list):
        refusals.add("COMMAND_EVIDENCE_INVALID")
        return []
    commands: list[ExecutionCommandV1] = []
    for item in raw:
        try:
            commands.append(ExecutionCommandV1.model_validate(item))
        except ValidationError:
            refusals.add("COMMAND_INVALID")
    return commands


def _parse_snapshot(raw: Any, *, name: str, refusals: set[str]) -> AccountSnapshotV1 | None:
    if raw is None:
        refusals.add(f"{name}_MISSING")
        return None
    try:
        return AccountSnapshotV1.model_validate(raw)
    except ValidationError:
        refusals.add(f"{name}_INVALID")
        return None


def _command_snapshot_id(command: ExecutionCommandV1) -> str | None:
    guards = command.guards
    if isinstance(guards, CommandGuards):
        return guards.risk_snapshot_id
    if isinstance(guards, EngineeringDemoCanaryGuards):
        return guards.account_snapshot_id
    return None


def check_command_envelope(command: ExecutionCommandV1, envelope: CanaryEnvelopeV1, refusals: set[str]) -> None:
    if command.executor_binding.execution_mode is not ExecutorMode(envelope.ACCOUNT):
        refusals.add("EXECUTOR_NOT_DEMO")
    if isinstance(command.source, ShadowAcceptanceSource):
        refusals.add("COMMAND_SOURCE_NOT_EXECUTABLE")
    if command.action not in ENTRY_ACTIONS or command.order is None:
        refusals.add("COMMAND_ACTION_NOT_SINGLE_ENTRY")
    guards = command.guards
    max_submit = getattr(guards, "max_submit_attempts", None)
    if max_submit is None or max_submit > envelope.MAX_SUBMIT:
        refusals.add("MAX_SUBMIT_EXCEEDED")
    if isinstance(guards, EngineeringDemoCanaryGuards) and guards.broker_execution != envelope.ACCOUNT + "_ONLY":
        refusals.add("EXECUTOR_NOT_DEMO")
    if command.revision != 1 and not envelope.AUTO_RETRY:
        # A revised command for the same idempotency key is a retry/re-issue.
        refusals.add("AUTO_RETRY_REVISION_PRESENT")
    if not envelope.PYRAMIDING:
        if isinstance(command.source, CommandSource) and command.source.block_role != "PARENT":
            refusals.add("PYRAMIDING_NON_PARENT_ROLE")
        order = command.order
        if order is not None and (order.broker_position_id is not None or order.broker_order_ticket is not None):
            refusals.add("PYRAMIDING_EXISTING_BROKER_REFERENCE")


def _check_account(raw: Any, envelope: CanaryEnvelopeV1, refusals: set[str]) -> None:
    if raw is None:
        refusals.add("ACCOUNT_EVIDENCE_MISSING")
        return
    if not isinstance(raw, Mapping):
        refusals.add("ACCOUNT_EVIDENCE_INVALID")
        return
    trade_mode = raw.get("trade_mode")
    expected = MT5_ACCOUNT_TRADE_MODE_DEMO if envelope.ACCOUNT == "DEMO" else None
    if type(trade_mode) is not int or trade_mode != expected:
        refusals.add("ACCOUNT_NOT_DEMO")


def _check_flat(snapshot: AccountSnapshotV1, envelope: CanaryEnvelopeV1, refusals: set[str]) -> None:
    if not snapshot.trade_allowed or not snapshot.autotrading_enabled:
        refusals.add("TERMINAL_TRADING_DISABLED")
    if envelope.FLAT_STATE_REQUIRED or not envelope.MULTIPLE_POSITION:
        if snapshot.open_positions:
            refusals.add("NOT_FLAT_OPEN_POSITIONS")
        if snapshot.pending_orders:
            refusals.add("NOT_FLAT_PENDING_ORDERS")


def _check_latest_state_veto(
    bundle: Mapping[str, Any],
    command: ExecutionCommandV1 | None,
    pinned: AccountSnapshotV1 | None,
    refusals: set[str],
    veto: LatestStateVeto,
) -> None:
    record = bundle.get("latest_state_veto")
    latest_raw = bundle.get("latest_snapshot")
    if record is None or latest_raw is None:
        refusals.add("LATEST_STATE_VETO_EVIDENCE_MISSING")
        return
    if not isinstance(record, Mapping) or set(record) != {"pinned_snapshot_id", "latest_snapshot_id", "result"}:
        refusals.add("LATEST_STATE_VETO_EVIDENCE_INVALID")
        return
    latest = _parse_snapshot(latest_raw, name="LATEST_SNAPSHOT", refusals=refusals)
    if latest is None or pinned is None or command is None or command.order is None:
        refusals.add("LATEST_STATE_VETO_NOT_EVALUABLE")
        return
    recomputed = veto(
        latest,
        pinned,
        canonical_symbol=command.order.canonical_symbol,
        broker_symbol=command.order.broker_symbol,
    )
    if (
        record["pinned_snapshot_id"] != pinned.snapshot_id
        or record["latest_snapshot_id"] != latest.snapshot_id
        or record["result"] != recomputed
    ):
        refusals.add("LATEST_STATE_VETO_RECORD_MISMATCH")
    if recomputed is not None:
        refusals.add("LATEST_STATE_VETOED")


def _check_ea_final_preflight(raw: Any, refusals: set[str]) -> None:
    if raw is None:
        refusals.add("EA_FINAL_PREFLIGHT_EVIDENCE_MISSING")
        return
    if not isinstance(raw, Mapping) or raw.get("final_preflight") != "REQUIRED":
        refusals.add("EA_FINAL_PREFLIGHT_EVIDENCE_INVALID")
        return
    if raw.get("ea_version") != ENGINEERING_DEMO_CANARY_EA_VERSION:
        refusals.add("EA_FINAL_PREFLIGHT_EA_VERSION_MISMATCH")


def _bundle_digest(bundle: Mapping[str, Any]) -> str | None:
    try:
        return evidence_digest(dict(bundle))
    except (TypeError, ValueError):
        return None


def check_presubmit_bundle(
    bundle: Mapping[str, Any],
    *,
    envelope: CanaryEnvelopeV1,
    latest_state_veto: LatestStateVeto | None = None,
) -> dict[str, Any]:
    """Return a decision; ``WITHIN_ENVELOPE`` only when every check held and nothing was missing."""

    refusals: set[str] = set()
    pinned_envelope = envelope_sha256(envelope)
    if bundle.get("schema_version") != PRESUBMIT_BUNDLE_SCHEMA:
        refusals.add("BUNDLE_SCHEMA_INVALID")
    if bundle.get("envelope_sha256") is None:
        refusals.add("ENVELOPE_SHA256_MISSING")
    elif bundle.get("envelope_sha256") != pinned_envelope:
        refusals.add("ENVELOPE_SHA256_MISMATCH")

    _check_account(bundle.get("account"), envelope, refusals)

    commands = _parse_commands(bundle.get("commands"), refusals)
    if bundle.get("commands") is not None and not commands and "COMMAND_INVALID" not in refusals:
        refusals.add("NO_COMMAND")
    if len(commands) > envelope.MAX_SUBMIT:
        refusals.add("MULTIPLE_COMMANDS")
    if len({command.idempotency_key for command in commands}) != len(commands):
        refusals.add("DUPLICATE_IDEMPOTENCY_KEY")
    for command in commands:
        check_command_envelope(command, envelope, refusals)
    command = commands[0] if len(commands) == 1 else None

    pinned = _parse_snapshot(bundle.get("pinned_snapshot"), name="PINNED_SNAPSHOT", refusals=refusals)
    if pinned is not None:
        _check_flat(pinned, envelope, refusals)
        for item in commands:
            if (
                item.executor_binding.executor_id != pinned.executor_id
                or item.executor_binding.account_id != pinned.account_id
                or _command_snapshot_id(item) != pinned.snapshot_id
            ):
                refusals.add("COMMAND_SNAPSHOT_BINDING_MISMATCH")

    if envelope.LATEST_STATE_VETO == "REQUIRED":
        _check_latest_state_veto(bundle, command, pinned, refusals, latest_state_veto or _canonical_latest_state_veto())
    if envelope.EA_FINAL_PREFLIGHT == "REQUIRED":
        _check_ea_final_preflight(bundle.get("ea_final_preflight"), refusals)

    return {
        "schema_version": ENVELOPE_DECISION_SCHEMA,
        "envelope_sha256": pinned_envelope,
        "bundle_sha256": _bundle_digest(bundle),
        "status": "REFUSED" if refusals else "WITHIN_ENVELOPE",
        "refusals": sorted(refusals),
        "SUBMIT_AUTHORITY": False,
    }


__all__ = [
    "ENVELOPE_DECISION_SCHEMA",
    "ENVELOPE_SCHEMA",
    "ENVELOPE_V1_PATH",
    "ENVELOPE_V1_SHA256",
    "PRESUBMIT_BUNDLE_SCHEMA",
    "CanaryEnvelopeV1",
    "EnvelopeError",
    "check_command_envelope",
    "check_presubmit_bundle",
    "envelope_sha256",
    "load_envelope",
]
