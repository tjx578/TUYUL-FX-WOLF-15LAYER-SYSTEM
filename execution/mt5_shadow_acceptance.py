"""Dedicated authority for signed, broker-forbidden MT5 SHADOW acceptance."""

from __future__ import annotations

import csv
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.mt5_execution_protocol import (
    PROTOCOL_VERSION,
    SHADOW_ACCEPTANCE_EA_VERSION,
    SHADOW_ACCEPTANCE_OPERATOR_AUTHORITY,
    SHADOW_ACCEPTANCE_PURPOSE,
    SHADOW_ACCEPTANCE_SCHEMA_VERSION,
    ExecutionAction,
    ExecutionCommandV1,
    ExecutorBinding,
    ExecutorMode,
    ShadowAcceptanceGuards,
    ShadowAcceptanceSource,
    sign_execution_command,
)
from execution.mt5_command_repository import CommandConflictError, MT5CommandRepository

SHADOW_ACCEPTANCE_MANIFEST_VERSION: Final = "wolf15.mt5.shadow-acceptance-manifest.v1"
SHADOW_ACCEPTANCE_UNIVERSE: Final = "WOLF15_XM_30_V1"
MAX_ACCEPTANCE_TTL_SECONDS: Final = 900
MAX_RUNTIME_AGE_SECONDS: Final = 30.0
_BROKER_MAP: Final = (
    Path(__file__).resolve().parents[1] / "ea_interface" / "wolf15_executor" / "broker_maps" / "xmglobal-mt5-10.csv"
)


class ShadowAcceptanceError(RuntimeError):
    """Fail-closed issuance failure."""


class ShadowAcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    acceptance_run_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
    operator_authority: Literal["WOLF15_SHADOW_ACCEPTANCE_OPERATOR_V1"] = SHADOW_ACCEPTANCE_OPERATOR_AUTHORITY
    purpose: Literal["BROKER_CONNECTED_SHADOW_VALIDATION"] = SHADOW_ACCEPTANCE_PURPOSE
    phase: Literal["A1", "A2"]
    executor_id: UUID
    issued_at_utc: datetime
    expires_at_utc: datetime

    @field_validator("issued_at_utc", "expires_at_utc")
    @classmethod
    def _utc_times(cls, value: datetime, info: Any) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{info.field_name} must include a UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _bounded_window(self) -> ShadowAcceptanceRequest:
        ttl = (self.expires_at_utc - self.issued_at_utc).total_seconds()
        if not 0 < ttl <= MAX_ACCEPTANCE_TTL_SECONDS:
            raise ValueError(f"acceptance TTL must be in (0, {MAX_ACCEPTANCE_TTL_SECONDS}] seconds")
        return self


def _age_seconds(value: datetime, *, now: datetime) -> float:
    return (now - value.astimezone(UTC)).total_seconds()


def _selected_symbol_pairs(
    request: ShadowAcceptanceRequest,
    snapshot_pairs: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    try:
        with _BROKER_MAP.open(newline="", encoding="utf-8-sig") as handle:
            frozen_pairs = tuple(
                (str(row["canonical_symbol"]).strip(), str(row["broker_symbol"]).strip())
                for row in csv.DictReader(handle)
            )
    except (OSError, KeyError) as exc:
        raise ShadowAcceptanceError("frozen broker symbol map is unavailable") from exc
    if len(frozen_pairs) != 30 or snapshot_pairs != frozen_pairs:
        raise ShadowAcceptanceError("executor snapshot is not the frozen 30-symbol universe")
    if request.phase == "A1":
        selected = tuple(pair for pair in snapshot_pairs if pair[0] == "EURUSD")
        if len(selected) != 1:
            raise ShadowAcceptanceError("A1 requires exactly one EURUSD symbol binding")
        return selected
    return snapshot_pairs


def build_shadow_acceptance_commands(
    request: ShadowAcceptanceRequest,
    *,
    executor: dict[str, Any],
    snapshot: Any,
    signing_secret: str | bytes,
    signing_key_id: str,
) -> tuple[ExecutionCommandV1, ...]:
    """Build signed RECONCILE_ONLY commands with no production-risk lineage."""

    if str(executor.get("executor_id")) != str(request.executor_id):
        raise ShadowAcceptanceError("executor identity does not match the acceptance request")
    if str(executor.get("execution_mode")) != ExecutorMode.SHADOW.value:
        raise ShadowAcceptanceError("executor is not SHADOW")
    if str(executor.get("ea_version")) != SHADOW_ACCEPTANCE_EA_VERSION:
        raise ShadowAcceptanceError("executor is not running the acceptance-capable EA")
    if str(executor.get("protocol_version")) != PROTOCOL_VERSION:
        raise ShadowAcceptanceError("executor protocol is incompatible")
    if snapshot.executor_id != request.executor_id or snapshot.account_id != executor.get("account_id"):
        raise ShadowAcceptanceError("account snapshot does not match executor identity")
    pairs = tuple((item.canonical_symbol, item.broker_symbol) for item in snapshot.symbols)
    selected = _selected_symbol_pairs(request, pairs)
    commands: list[ExecutionCommandV1] = []
    for canonical_symbol, broker_symbol in selected:
        command_id = uuid4()
        payload: dict[str, Any] = {
            "event": "execution_command",
            "protocol_version": PROTOCOL_VERSION,
            "command_id": command_id,
            "idempotency_key": ":".join(
                (str(executor["account_id"]), "shadow-acceptance", request.acceptance_run_id, canonical_symbol)
            ),
            "revision": 1,
            "issued_at_utc": request.issued_at_utc,
            "not_before_utc": request.issued_at_utc,
            "expires_at_utc": request.expires_at_utc,
            "executor_binding": ExecutorBinding(
                executor_id=request.executor_id,
                account_id=str(executor["account_id"]),
                login_hash=str(executor["login_hash"]),
                broker_server=str(executor["broker_server"]),
                execution_mode=ExecutorMode.SHADOW,
            ),
            "source": ShadowAcceptanceSource(
                source_schema_version=SHADOW_ACCEPTANCE_SCHEMA_VERSION,
                acceptance_run_id=request.acceptance_run_id,
                operator_authority=request.operator_authority,
                purpose=request.purpose,
                phase=request.phase,
                canonical_symbol=canonical_symbol,
                broker_symbol=broker_symbol,
                execution_authority=False,
                broker_execution="FORBIDDEN",
            ),
            "action": ExecutionAction.RECONCILE_ONLY,
            "order": None,
            "guards": ShadowAcceptanceGuards(
                expected_margin_mode=snapshot.margin_mode,
                account_snapshot_id=snapshot.snapshot_id,
                balance_snapshot=snapshot.balance,
                equity_snapshot=snapshot.equity,
            ),
        }
        commands.append(sign_execution_command(payload, secret=signing_secret, key_id=signing_key_id))
    return tuple(commands)


def acceptance_manifest(
    request: ShadowAcceptanceRequest,
    *,
    executor: dict[str, Any],
    commands: tuple[ExecutionCommandV1, ...],
) -> dict[str, Any]:
    """Return identity and lineage only; credentials never enter this object."""

    command_rows: list[dict[str, str]] = []
    for command in commands:
        source = command.source
        if (
            not isinstance(source, ShadowAcceptanceSource)
            or source.acceptance_run_id != request.acceptance_run_id
            or source.phase != request.phase
            or command.executor_binding.executor_id != request.executor_id
        ):
            raise ShadowAcceptanceError("manifest command lineage is inconsistent")
        command_rows.append(
            {
                "canonical_symbol": source.canonical_symbol,
                "broker_symbol": source.broker_symbol,
                "command_id": str(command.command_id),
            }
        )
    expected_count = 1 if request.phase == "A1" else 30
    if len(command_rows) != expected_count:
        raise ShadowAcceptanceError("manifest command count is inconsistent")
    return {
        "schema_version": SHADOW_ACCEPTANCE_MANIFEST_VERSION,
        "acceptance_run_id": request.acceptance_run_id,
        "operator_authority": request.operator_authority,
        "purpose": request.purpose,
        "phase": request.phase,
        "symbol_universe": SHADOW_ACCEPTANCE_UNIVERSE,
        "executor_id": str(request.executor_id),
        "broker_server": str(executor["broker_server"]),
        "expected_ea_version": SHADOW_ACCEPTANCE_EA_VERSION,
        "expected_protocol_version": PROTOCOL_VERSION,
        "started_at_utc": request.issued_at_utc.isoformat(),
        "expires_at_utc": request.expires_at_utc.isoformat(),
        "commands": command_rows,
    }


class ShadowAcceptanceAuthorityV1:
    """Issue one atomic A1/A2 acceptance run under engaged governance."""

    def __init__(self, repository: MT5CommandRepository) -> None:
        self._repository = repository

    async def issue(self, request: ShadowAcceptanceRequest) -> dict[str, Any]:
        now = datetime.now(UTC)
        if request.issued_at_utc > now + timedelta(seconds=5) or request.expires_at_utc <= now:
            raise ShadowAcceptanceError("acceptance run is not currently active")
        signed_wire = await self._repository.signed_wire_schema_status()
        acceptance_schema = await self._repository.shadow_acceptance_schema_status()
        if not signed_wire.get("ready") or not acceptance_schema.get("ready"):
            raise ShadowAcceptanceError("acceptance database schema is not ready")
        executor = await self._repository.get_executor(request.executor_id)
        governance = await self._repository.governance_snapshot(request.executor_id)
        if governance.execution_mode != ExecutorMode.SHADOW.value:
            raise ShadowAcceptanceError("governed executor is not SHADOW")
        if not governance.kill_switch_active:
            raise ShadowAcceptanceError("global kill switch must remain engaged")
        heartbeat = executor.get("last_heartbeat_at")
        heartbeat_age = _age_seconds(heartbeat, now=now) if isinstance(heartbeat, datetime) else None
        if heartbeat_age is None or not -5 <= heartbeat_age <= MAX_RUNTIME_AGE_SECONDS:
            raise ShadowAcceptanceError("executor heartbeat is missing or stale")
        snapshot = await self._repository.latest_snapshot(request.executor_id)
        if snapshot is None:
            raise ShadowAcceptanceError("executor account snapshot is missing or stale")
        snapshot_age = _age_seconds(snapshot.captured_at_utc, now=now)
        if not -5 <= snapshot_age <= MAX_RUNTIME_AGE_SECONDS:
            raise ShadowAcceptanceError("executor account snapshot is missing or stale")
        if snapshot.open_positions:
            raise ShadowAcceptanceError("acceptance requires zero open broker positions")
        secret = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET", "").strip()
        key_id = os.getenv("EXECUTOR_COMMAND_SIGNING_KEY_ID", "").strip()
        if len(secret.encode("utf-8")) < 32 or not key_id:
            raise ShadowAcceptanceError("acceptance signing authority is unavailable")
        commands = build_shadow_acceptance_commands(
            request,
            executor=executor,
            snapshot=snapshot,
            signing_secret=secret,
            signing_key_id=key_id,
        )
        try:
            await self._repository.enqueue_shadow_acceptance_commands(commands)
        except CommandConflictError as exc:
            raise ShadowAcceptanceError(str(exc)) from exc
        return acceptance_manifest(request, executor=executor, commands=commands)


__all__ = [
    "SHADOW_ACCEPTANCE_EA_VERSION",
    "SHADOW_ACCEPTANCE_MANIFEST_VERSION",
    "SHADOW_ACCEPTANCE_UNIVERSE",
    "ShadowAcceptanceAuthorityV1",
    "ShadowAcceptanceError",
    "ShadowAcceptanceRequest",
    "acceptance_manifest",
    "build_shadow_acceptance_commands",
]
