"""Fail-closed authority for one non-strategy MT5 DEMO execution canary."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.mt5_execution_protocol import (
    ENGINEERING_DEMO_CANARY_EA_VERSION,
    ENGINEERING_DEMO_CANARY_MAGIC,
    ENGINEERING_DEMO_CANARY_OPERATOR_AUTHORITY,
    ENGINEERING_DEMO_CANARY_PURPOSE,
    ENGINEERING_DEMO_CANARY_SCHEMA_VERSION,
    PROTOCOL_VERSION,
    AccountSnapshotV1,
    EngineeringDemoCanaryGuards,
    EngineeringDemoCanarySource,
    ExecutionAction,
    ExecutionCommandV1,
    ExecutorBinding,
    ExecutorMode,
    OrderInstruction,
    sign_execution_command,
)
from execution.mt5_command_repository import CommandConflictError, MT5CommandRepository
from execution.mt5_demo_canary_authority_packet import (
    DemoCanaryAuthorityPacketV1,
    IssuanceDisposition,
    ProcessLocalIssuanceCapability,
    validate_authority_packet,
)

ENGINEERING_DEMO_CANARY_MANIFEST_VERSION: Final = "wolf15.mt5.engineering-demo-canary-manifest.v1"
MAX_CANARY_TTL_SECONDS: Final = 120
MAX_RUNTIME_AGE_SECONDS: Final = 30.0
_FEATURE_FLAG: Final = "WOLF15_ENABLE_ENGINEERING_DEMO_CANARY_ISSUANCE"


class EngineeringDemoCanaryError(RuntimeError):
    """A D0 canary failed a safety or lineage precondition."""


class EngineeringDemoCanaryRequest(BaseModel):
    """Exact one-order scope approved by an operator for code-level issuance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canary_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
    command_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=3, max_length=240)
    operator_authority: Literal["WOLF15_ENGINEERING_DEMO_OPERATOR_V1"] = ENGINEERING_DEMO_CANARY_OPERATOR_AUTHORITY
    purpose: Literal["EXECUTION_PLUMBING_VALIDATION"] = ENGINEERING_DEMO_CANARY_PURPOSE
    executor_id: UUID
    approved_account_id: str = Field(..., min_length=1, max_length=100)
    approved_broker_server: str = Field(..., min_length=1, max_length=200)
    approved_canonical_symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    approved_broker_symbol: str = Field(..., min_length=1, max_length=64)
    expected_account_snapshot_id: str = Field(..., min_length=3, max_length=200)
    side: Literal["BUY", "SELL"]
    volume: float = Field(..., gt=0, le=1000)
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    max_spread_points: int = Field(..., ge=0, le=100_000)
    max_price_drift_points: int = Field(..., ge=0, le=100_000)
    max_slippage_points: int | None = Field(default=None, ge=0, le=100_000)
    magic_number: int = Field(default=ENGINEERING_DEMO_CANARY_MAGIC, ge=1, le=2_147_483_647)
    issued_at_utc: datetime
    expires_at_utc: datetime

    @field_validator("issued_at_utc", "expires_at_utc")
    @classmethod
    def _utc_times(cls, value: datetime, info: Any) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{info.field_name} must include a UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _bounded_window_and_prices(self) -> EngineeringDemoCanaryRequest:
        ttl = (self.expires_at_utc - self.issued_at_utc).total_seconds()
        if not 0 < ttl <= MAX_CANARY_TTL_SECONDS:
            raise ValueError(f"canary TTL must be in (0, {MAX_CANARY_TTL_SECONDS}] seconds")
        if self.side == "BUY" and not self.stop_loss < self.entry_price < self.take_profit:
            raise ValueError("BUY canary requires stop_loss < entry_price < take_profit")
        if self.side == "SELL" and not self.take_profit < self.entry_price < self.stop_loss:
            raise ValueError("SELL canary requires take_profit < entry_price < stop_loss")
        if self.max_slippage_points is not None and self.max_slippage_points != self.max_price_drift_points:
            raise ValueError("current DEMO wire requires max_slippage_points to equal max_price_drift_points")
        if self.magic_number != ENGINEERING_DEMO_CANARY_MAGIC:
            raise ValueError("engineering DEMO canary magic number is fixed")
        return self


def _age_seconds(value: datetime, *, now: datetime) -> float:
    return (now - value.astimezone(UTC)).total_seconds()


def _exact_minimum_volume(requested: float, minimum: float, step: float) -> bool:
    requested_value = Decimal(str(requested))
    minimum_value = Decimal(str(minimum))
    step_value = Decimal(str(step))
    if requested_value != minimum_value or step_value <= 0:
        return False
    return (requested_value - minimum_value) % step_value == 0


def _comment_tag(canary_id: str) -> str:
    digest = hashlib.sha256(canary_id.encode("ascii")).hexdigest()[:12]
    return f"W15D0:{digest}"


def build_engineering_demo_canary_command(
    request: EngineeringDemoCanaryRequest,
    *,
    executor: dict[str, Any],
    snapshot: AccountSnapshotV1,
    signing_secret: str | bytes,
    signing_key_id: str,
) -> ExecutionCommandV1:
    """Build one signed market command whose lineage can never count as strategy evidence."""

    if str(executor.get("executor_id")) != str(request.executor_id):
        raise EngineeringDemoCanaryError("executor identity does not match canary approval")
    if executor.get("account_id") != request.approved_account_id:
        raise EngineeringDemoCanaryError("executor account does not match canary approval")
    if executor.get("broker_server") != request.approved_broker_server:
        raise EngineeringDemoCanaryError("executor broker server does not match canary approval")
    if str(executor.get("execution_mode")) != ExecutorMode.DEMO.value:
        raise EngineeringDemoCanaryError("engineering canary requires a DEMO executor")
    if str(executor.get("ea_version")) != ENGINEERING_DEMO_CANARY_EA_VERSION:
        raise EngineeringDemoCanaryError("executor is not running the dedicated DEMO EA")
    if str(executor.get("protocol_version")) != PROTOCOL_VERSION:
        raise EngineeringDemoCanaryError("executor protocol is incompatible")
    if snapshot.executor_id != request.executor_id or snapshot.account_id != request.approved_account_id:
        raise EngineeringDemoCanaryError("account snapshot does not match approved executor binding")
    if snapshot.snapshot_id != request.expected_account_snapshot_id:
        raise EngineeringDemoCanaryError("account snapshot identity differs from operator approval")
    if not snapshot.trade_allowed or not snapshot.autotrading_enabled:
        raise EngineeringDemoCanaryError("DEMO terminal trading is not enabled")
    if not snapshot.broker_ledger_reconciled:
        raise EngineeringDemoCanaryError("direct broker ledger is not reconciled")
    if snapshot.open_positions or snapshot.pending_orders:
        raise EngineeringDemoCanaryError("engineering canary requires a flat DEMO account")

    capabilities = [
        item
        for item in snapshot.symbols
        if item.canonical_symbol == request.approved_canonical_symbol
        and item.broker_symbol == request.approved_broker_symbol
    ]
    if len(capabilities) != 1:
        raise EngineeringDemoCanaryError("approved symbol mapping is absent or ambiguous")
    capability = capabilities[0]
    if not _exact_minimum_volume(request.volume, capability.volume_min, capability.volume_step):
        raise EngineeringDemoCanaryError("canary volume must equal the broker minimum exactly")

    payload: dict[str, Any] = {
        "event": "execution_command",
        "protocol_version": PROTOCOL_VERSION,
        "command_id": request.command_id or uuid4(),
        "idempotency_key": request.idempotency_key
        or ":".join((request.approved_account_id, "engineering-demo-canary", request.canary_id, "PLACE_MARKET")),
        "revision": 1,
        "issued_at_utc": request.issued_at_utc,
        "not_before_utc": request.issued_at_utc,
        "expires_at_utc": request.expires_at_utc,
        "executor_binding": ExecutorBinding(
            executor_id=request.executor_id,
            account_id=request.approved_account_id,
            login_hash=str(executor["login_hash"]),
            broker_server=request.approved_broker_server,
            execution_mode=ExecutorMode.DEMO,
        ),
        "source": EngineeringDemoCanarySource(
            source_schema_version=ENGINEERING_DEMO_CANARY_SCHEMA_VERSION,
            canary_id=request.canary_id,
            operator_authority=request.operator_authority,
            purpose=request.purpose,
            approved_executor_id=request.executor_id,
            approved_account_id=request.approved_account_id,
            approved_broker_server=request.approved_broker_server,
            approved_canonical_symbol=request.approved_canonical_symbol,
            approved_broker_symbol=request.approved_broker_symbol,
        ),
        "action": ExecutionAction.PLACE_MARKET,
        "order": OrderInstruction(
            canonical_symbol=request.approved_canonical_symbol,
            broker_symbol=request.approved_broker_symbol,
            side=request.side,
            order_type=request.side,
            volume=request.volume,
            entry_price=request.entry_price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            magic=request.magic_number,
            comment_tag=_comment_tag(request.canary_id),
            time_in_force="GTC",
        ),
        "guards": EngineeringDemoCanaryGuards(
            expected_margin_mode=snapshot.margin_mode,
            account_snapshot_id=snapshot.snapshot_id,
            balance_snapshot=snapshot.balance,
            equity_snapshot=snapshot.equity,
            max_spread_points=request.max_spread_points,
            max_price_drift_points=request.max_price_drift_points,
        ),
    }
    return sign_execution_command(payload, secret=signing_secret, key_id=signing_key_id)


def engineering_demo_canary_manifest(
    request: EngineeringDemoCanaryRequest,
    *,
    command: ExecutionCommandV1,
) -> dict[str, Any]:
    source = command.source
    if not isinstance(source, EngineeringDemoCanarySource) or source.canary_id != request.canary_id:
        raise EngineeringDemoCanaryError("canary manifest lineage is inconsistent")
    return {
        "schema_version": ENGINEERING_DEMO_CANARY_MANIFEST_VERSION,
        "canary_id": request.canary_id,
        "command_id": str(command.command_id),
        "command_source_class": source.command_source_class,
        "executor_id": str(source.approved_executor_id),
        "account_id": source.approved_account_id,
        "broker_server": source.approved_broker_server,
        "canonical_symbol": source.approved_canonical_symbol,
        "broker_symbol": source.approved_broker_symbol,
        "max_broker_effects": source.max_broker_effects,
        "demo_only": source.demo_only,
        "strategy_authority": source.strategy_authority,
        "strategy_scorecard_eligible": source.strategy_scorecard_eligible,
        "research_result_eligible": source.research_result_eligible,
        "live_real_money_allowed": source.live_real_money_allowed,
        "issued_at_utc": command.issued_at_utc.isoformat(),
        "expires_at_utc": command.expires_at_utc.isoformat(),
    }


class EngineeringDemoCanaryAuthorityV1:
    """Queue one D0 command while the global kill switch remains engaged."""

    def __init__(self, repository: MT5CommandRepository) -> None:
        self._repository = repository

    @staticmethod
    def _require_enabled() -> None:
        if os.getenv(_FEATURE_FLAG, "").strip().lower() != "true":
            raise EngineeringDemoCanaryError("engineering DEMO canary issuance is disabled")

    async def issue(self, request: EngineeringDemoCanaryRequest) -> dict[str, Any]:
        del request
        raise EngineeringDemoCanaryError("legacy unbound issuance is disabled; use issue_frozen")

    async def issue_frozen(
        self,
        packet: DemoCanaryAuthorityPacketV1,
        *,
        expected_packet_sha256: str,
        capability: ProcessLocalIssuanceCapability,
    ) -> dict[str, Any]:
        """Issue only the exact operator-frozen packet under one process capability."""

        now = datetime.now(UTC)
        digest = validate_authority_packet(packet, expected_sha256=expected_packet_sha256, now=now)
        if capability.consumed:
            return {
                "schema_version": ENGINEERING_DEMO_CANARY_MANIFEST_VERSION,
                "authority_packet_sha256": digest,
                "command_id": str(packet.command_id),
                "disposition": IssuanceDisposition.ALREADY_ISSUED.value,
            }
        request = EngineeringDemoCanaryRequest(
            canary_id=packet.canary_id,
            command_id=packet.command_id,
            idempotency_key=packet.idempotency_key,
            executor_id=packet.executor_id,
            approved_account_id=packet.account_reference,
            approved_broker_server=packet.broker_server,
            approved_canonical_symbol=packet.canonical_symbol,
            approved_broker_symbol=packet.broker_symbol,
            expected_account_snapshot_id=packet.expected_account_snapshot_id,
            side=packet.side,
            volume=float(packet.volume),
            entry_price=float(packet.entry_price),
            stop_loss=float(packet.stop_loss),
            take_profit=float(packet.take_profit),
            max_spread_points=packet.max_spread_points,
            max_price_drift_points=packet.max_price_drift_points,
            max_slippage_points=packet.max_slippage_points,
            magic_number=packet.magic_number,
            issued_at_utc=packet.issued_at_utc,
            expires_at_utc=packet.expires_at_utc,
        )
        result = await self._issue_frozen_request(request, packet=packet, packet_sha256_value=digest)
        capability.mark_consumed(packet, packet_sha256_value=digest)
        result["authority_packet_sha256"] = digest
        result["command_content_sha256"] = packet.command_content_sha256
        return result

    async def _issue_frozen_request(
        self,
        request: EngineeringDemoCanaryRequest,
        *,
        packet: DemoCanaryAuthorityPacketV1,
        packet_sha256_value: str,
    ) -> dict[str, Any]:
        """Run existing runtime checks, then persist packet and command atomically."""

        now = datetime.now(UTC)
        schema = await self._repository.d0_canary_control_schema_status()
        if not schema.get("ready"):
            raise EngineeringDemoCanaryError("engineering canary database schema is not ready")
        executor = await self._repository.get_executor(request.executor_id)
        governance = await self._repository.governance_snapshot(request.executor_id)
        if governance.execution_mode != ExecutorMode.DEMO.value or not governance.kill_switch_active:
            raise EngineeringDemoCanaryError("frozen canary requires governed DEMO mode and engaged kill switch")
        heartbeat = executor.get("last_heartbeat_at")
        heartbeat_age = _age_seconds(heartbeat, now=now) if isinstance(heartbeat, datetime) else None
        if heartbeat_age is None or not -5 <= heartbeat_age <= MAX_RUNTIME_AGE_SECONDS:
            raise EngineeringDemoCanaryError("executor heartbeat is missing or stale")
        snapshot = await self._repository.latest_snapshot(request.executor_id)
        if snapshot is None or not -5 <= _age_seconds(snapshot.captured_at_utc, now=now) <= MAX_RUNTIME_AGE_SECONDS:
            raise EngineeringDemoCanaryError("executor account snapshot is missing or stale")
        secret = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET", "").strip()
        key_id = os.getenv("EXECUTOR_COMMAND_SIGNING_KEY_ID", "").strip()
        if len(secret.encode("utf-8")) < 32 or not key_id:
            raise EngineeringDemoCanaryError("canary signing authority is unavailable")
        command = build_engineering_demo_canary_command(
            request,
            executor=executor,
            snapshot=snapshot,
            signing_secret=secret,
            signing_key_id=key_id,
        )
        try:
            disposition = await self._repository.enqueue_frozen_engineering_demo_canary_command(
                command,
                authority_packet=packet,
                authority_packet_sha256=packet_sha256_value,
            )
        except CommandConflictError as exc:
            raise EngineeringDemoCanaryError(str(exc)) from exc
        manifest = engineering_demo_canary_manifest(request, command=command)
        manifest["disposition"] = str(disposition)
        return manifest

    async def arm(
        self,
        canary_id: str,
        *,
        actor: str,
        reason: str,
        expected_governance_version: int | None = None,
    ) -> dict[str, Any]:
        """Open the pre-created one-shot window; no command is built here."""

        self._require_enabled()
        try:
            return await self._repository.arm_engineering_demo_canary(
                canary_id,
                actor=actor,
                reason=reason,
                expected_governance_version=expected_governance_version,
            )
        except CommandConflictError as exc:
            raise EngineeringDemoCanaryError(str(exc)) from exc


__all__ = [
    "ENGINEERING_DEMO_CANARY_MAGIC",
    "ENGINEERING_DEMO_CANARY_MANIFEST_VERSION",
    "MAX_CANARY_TTL_SECONDS",
    "EngineeringDemoCanaryAuthorityV1",
    "EngineeringDemoCanaryError",
    "EngineeringDemoCanaryRequest",
    "build_engineering_demo_canary_command",
    "engineering_demo_canary_manifest",
]
