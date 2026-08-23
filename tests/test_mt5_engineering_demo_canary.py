from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from contracts.mt5_execution_protocol import (
    ENGINEERING_DEMO_CANARY_EA_VERSION,
    AccountSnapshotV1,
    EngineeringDemoCanaryGuards,
    EngineeringDemoCanarySource,
    ExecutionCommandV1,
    ExecutionReportV1,
    ExecutorMode,
    MarginMode,
    SymbolCapability,
    sha256_tag,
    verify_execution_command,
)
from execution.mt5_command_repository import (
    CommandConflictError,
    _validate_engineering_canary_report_evidence,
)
from execution.mt5_engineering_demo_canary import (
    EngineeringDemoCanaryAuthorityV1,
    EngineeringDemoCanaryError,
    EngineeringDemoCanaryRequest,
    build_engineering_demo_canary_command,
    engineering_demo_canary_manifest,
)
from scripts import issue_mt5_engineering_demo_canary as canary_cli

SECRET = "d" * 64
EXECUTOR_ID = UUID("11111111-1111-4111-8111-111111111111")
D0_MIGRATION = (
    Path(__file__).parents[1] / "storage" / "migrations" / "versions" / "20260823_01_engineering_demo_canary.py"
)


def _executor(**updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "executor_id": EXECUTOR_ID,
        "account_id": "demo-account-01",
        "login_hash": "sha256:" + "a" * 64,
        "broker_server": "Broker-Demo",
        "execution_mode": "DEMO",
        "ea_version": ENGINEERING_DEMO_CANARY_EA_VERSION,
        "protocol_version": "wolf15.mt5.exec.v1",
        "status": "ONLINE",
        "last_heartbeat_at": datetime.now(UTC),
    }
    values.update(updates)
    return values


def _snapshot(**updates: object) -> AccountSnapshotV1:
    values: dict[str, object] = {
        "snapshot_id": "snapshot-demo-001",
        "captured_at_utc": datetime.now(UTC),
        "executor_id": EXECUTOR_ID,
        "account_id": "demo-account-01",
        "currency": "USD",
        "balance": 1000.0,
        "equity": 1000.0,
        "floating_pnl": 0.0,
        "used_margin": 0.0,
        "free_margin": 1000.0,
        "margin_level_pct": None,
        "margin_mode": MarginMode.HEDGING,
        "trade_allowed": True,
        "autotrading_enabled": True,
        "open_positions": [],
        "pending_orders": [],
        "broker_ledger_reconciled": True,
        "symbols": [
            SymbolCapability(
                canonical_symbol="EURUSD",
                broker_symbol="EURUSD",
                digits=5,
                point=0.00001,
                tick_size=0.00001,
                tick_value_profit=1.0,
                tick_value_loss=1.0,
                volume_min=0.01,
                volume_max=100.0,
                volume_step=0.01,
                stops_level_points=0,
                freeze_level_points=0,
            )
        ],
    }
    values.update(updates)
    return AccountSnapshotV1.model_validate(values)


def _request(**updates: object) -> EngineeringDemoCanaryRequest:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "canary_id": "d0-canary-001",
        "executor_id": EXECUTOR_ID,
        "approved_account_id": "demo-account-01",
        "approved_broker_server": "Broker-Demo",
        "approved_canonical_symbol": "EURUSD",
        "approved_broker_symbol": "EURUSD",
        "expected_account_snapshot_id": "snapshot-demo-001",
        "side": "BUY",
        "volume": 0.01,
        "entry_price": 1.1000,
        "stop_loss": 1.0950,
        "take_profit": 1.1100,
        "max_spread_points": 25,
        "max_price_drift_points": 10,
        "issued_at_utc": now,
        "expires_at_utc": now + timedelta(seconds=90),
    }
    values.update(updates)
    return EngineeringDemoCanaryRequest.model_validate(values)


def _command(
    *,
    request: EngineeringDemoCanaryRequest | None = None,
    executor: dict[str, object] | None = None,
    snapshot: AccountSnapshotV1 | None = None,
) -> ExecutionCommandV1:
    return build_engineering_demo_canary_command(
        request or _request(),
        executor=executor or _executor(),
        snapshot=snapshot or _snapshot(),
        signing_secret=SECRET,
        signing_key_id="d0-test-key",
    )


def _report(
    command: ExecutionCommandV1,
    *,
    state: str,
    broker: dict[str, object] | None = None,
    execution: dict[str, object] | None = None,
) -> ExecutionReportV1:
    assert command.order is not None
    return ExecutionReportV1.model_validate(
        {
            "report_id": uuid4(),
            "command_id": command.command_id,
            "idempotency_key": command.idempotency_key,
            "sequence": 1,
            "state": state,
            "event_time_utc": datetime.now(UTC),
            "executor_id": command.executor_binding.executor_id,
            "account_id": command.executor_binding.account_id,
            "request_hash": sha256_tag(command.model_dump(mode="json")),
            "broker": {} if broker is None else broker,
            "execution": {
                "requested_volume": command.order.volume,
                "requested_price": command.order.entry_price,
                "stop_loss": command.order.stop_loss,
                "take_profit": command.order.take_profit,
            }
            if execution is None
            else execution,
            "reason_code": f"D0_{state}",
        }
    )


def test_canary_is_demo_only_non_strategy_one_parent_command() -> None:
    command = _command()

    assert command.executor_binding.execution_mode is ExecutorMode.DEMO
    assert isinstance(command.source, EngineeringDemoCanarySource)
    assert isinstance(command.guards, EngineeringDemoCanaryGuards)
    assert command.source.command_source_class == "ENGINEERING_DEMO_CANARY"
    assert command.source.strategy_authority is False
    assert command.source.strategy_scorecard_eligible is False
    assert command.source.research_result_eligible is False
    assert command.source.live_real_money_allowed is False
    assert command.source.demo_only is True
    assert command.source.order_role == "PARENT"
    assert command.source.max_broker_effects == 1
    assert command.guards.max_submit_attempts == 1
    assert command.guards.max_broker_effects == 1
    assert command.order is not None
    assert command.order.volume == 0.01
    assert command.order.magic == 150016
    assert command.order.time_in_force == "GTC"
    assert command.order.broker_expiration_utc is None
    assert command.order.comment_tag.startswith("W15D0:")
    assert verify_execution_command(command, secret=SECRET)


def test_canary_migration_owns_lineage_and_the_global_unresolved_slot() -> None:
    migration = D0_MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "20260823_01"' in migration
    assert 'down_revision = "20260813_02"' in migration
    assert "source_event = 'ENGINEERING_DEMO_CANARY'" in migration
    assert "payload #>> '{order,magic}' = '150016'" in migration
    assert "payload #>> '{order,time_in_force}' = 'GTC'" in migration
    assert "WHERE state IN ('QUEUED','ARMED','RECONCILIATION_REQUIRED')" in migration
    assert "max_broker_effects = 1" in migration


def test_canary_manifest_cannot_be_counted_as_strategy_or_real_money() -> None:
    request = _request()
    manifest = engineering_demo_canary_manifest(request, command=_command(request=request))

    assert manifest["command_source_class"] == "ENGINEERING_DEMO_CANARY"
    assert manifest["strategy_authority"] is False
    assert manifest["strategy_scorecard_eligible"] is False
    assert manifest["research_result_eligible"] is False
    assert manifest["live_real_money_allowed"] is False
    assert manifest["demo_only"] is True
    assert manifest["max_broker_effects"] == 1


@pytest.mark.parametrize(
    ("executor_update", "request_update", "message"),
    [
        ({"account_id": "wrong-account"}, {}, "account"),
        ({"broker_server": "Wrong-Server"}, {}, "broker server"),
        ({"execution_mode": "SHADOW"}, {}, "DEMO executor"),
        ({"ea_version": "0.22-shadow-acceptance-v1"}, {}, "dedicated DEMO EA"),
        ({}, {"approved_account_id": "wrong-account"}, "account"),
        ({}, {"approved_broker_server": "Wrong-Server"}, "broker server"),
    ],
)
def test_canary_rejects_binding_or_mode_drift(
    executor_update: dict[str, object],
    request_update: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(EngineeringDemoCanaryError, match=message):
        _command(request=_request(**request_update), executor=_executor(**executor_update))


def test_canary_rejects_wrong_symbol_mapping() -> None:
    with pytest.raises(EngineeringDemoCanaryError, match="symbol mapping"):
        _command(request=_request(approved_broker_symbol="EURUSD.other"))


def test_canary_rejects_more_than_broker_minimum_volume() -> None:
    with pytest.raises(EngineeringDemoCanaryError, match="broker minimum"):
        _command(request=_request(volume=0.02))


@pytest.mark.parametrize(
    ("snapshot_update", "message"),
    [
        ({"broker_ledger_reconciled": False}, "ledger"),
        ({"autotrading_enabled": False}, "trading"),
        ({"trade_allowed": False}, "trading"),
        (
            {
                "open_positions": [
                    {
                        "position_id": 1,
                        "symbol": "EURUSD",
                        "side": "BUY",
                        "volume": 0.01,
                        "entry_price": 1.1,
                        "current_price": 1.1,
                        "stop_loss": 1.095,
                        "take_profit": 1.11,
                        "magic": 150016,
                        "comment": "W15D0:existing",
                        "floating_pnl": 0.0,
                    }
                ]
            },
            "flat DEMO account",
        ),
    ],
)
def test_canary_rejects_unready_snapshot(snapshot_update: dict[str, object], message: str) -> None:
    with pytest.raises(EngineeringDemoCanaryError, match=message):
        _command(snapshot=_snapshot(**snapshot_update))


def test_canary_requires_mandatory_sl_and_tp() -> None:
    command = _command()
    raw = command.model_dump(mode="json")
    raw["order"]["stop_loss"] = None

    with pytest.raises(ValidationError):
        ExecutionCommandV1.model_validate(raw)


@pytest.mark.parametrize(
    "updates",
    [
        {"magic": 150015},
        {
            "time_in_force": "SPECIFIED",
            "broker_expiration_utc": datetime.now(UTC) + timedelta(minutes=1),
        },
    ],
)
def test_canary_requires_fixed_magic_and_gtc_lifetime(updates: dict[str, object]) -> None:
    raw = _command().model_dump(mode="json")
    raw["order"].update(updates)

    with pytest.raises(ValidationError, match="fixed magic and GTC"):
        ExecutionCommandV1.model_validate(raw)


def test_canary_cannot_be_relabelled_live_or_signal_json() -> None:
    command = _command()
    raw = command.model_dump(mode="json")
    raw["executor_binding"]["execution_mode"] = "LIVE"
    with pytest.raises(ValidationError, match="requires DEMO"):
        ExecutionCommandV1.model_validate(raw)

    raw = command.model_dump(mode="json")
    raw["source"]["source_event"] = "signal_json"
    with pytest.raises(ValidationError):
        ExecutionCommandV1.model_validate(raw)


def test_canary_signature_tamper_is_detected() -> None:
    command = _command()
    assert command.order is not None
    tampered = command.model_copy(update={"order": command.order.model_copy(update={"volume": 0.02})})

    assert verify_execution_command(tampered, secret=SECRET) is False


def test_canary_ttl_is_bounded() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="TTL"):
        _request(issued_at_utc=now, expires_at_utc=now + timedelta(seconds=121))


def test_d0_report_requires_exact_state_specific_broker_evidence() -> None:
    command = _command()
    assert command.order is not None

    _validate_engineering_canary_report_evidence(_report(command, state="SUBMITTING"), command)
    complete_fill = _report(
        command,
        state="FILLED",
        broker={
            "order_ticket": 700001,
            "deal_ticket": 800001,
            "position_id": 900001,
            "retcode": 10009,
        },
        execution={
            "requested_volume": command.order.volume,
            "filled_volume": command.order.volume,
            "requested_price": command.order.entry_price,
            "filled_price": command.order.entry_price,
            "stop_loss": command.order.stop_loss,
            "take_profit": command.order.take_profit,
        },
    )
    _validate_engineering_canary_report_evidence(complete_fill, command)
    with pytest.raises(CommandConflictError, match="order, deal, position"):
        _validate_engineering_canary_report_evidence(
            complete_fill.model_copy(update={"broker": complete_fill.broker.model_copy(update={"position_id": None})}),
            command,
        )
    with pytest.raises(CommandConflictError, match="requires reconciliation"):
        _validate_engineering_canary_report_evidence(_report(command, state="PARTIALLY_FILLED"), command)

    with pytest.raises(CommandConflictError, match="order ticket"):
        _validate_engineering_canary_report_evidence(_report(command, state="BROKER_ACCEPTED"), command)
    with pytest.raises(CommandConflictError, match="retcode"):
        _validate_engineering_canary_report_evidence(_report(command, state="BROKER_REJECTED"), command)
    with pytest.raises(CommandConflictError, match="volume"):
        _validate_engineering_canary_report_evidence(_report(command, state="FILLED", execution={}), command)
    with pytest.raises(CommandConflictError, match="server-authoritative"):
        _validate_engineering_canary_report_evidence(_report(command, state="EXPIRED"), command)
    with pytest.raises(CommandConflictError, match="deal and fill"):
        _validate_engineering_canary_report_evidence(
            _report(command, state="CLOSED_TP", broker={"position_id": 900001}), command
        )


def test_d0_report_rejects_requested_price_drift() -> None:
    command = _command()
    assert command.order is not None
    with pytest.raises(CommandConflictError, match="requested price"):
        _validate_engineering_canary_report_evidence(
            _report(
                command,
                state="SUBMITTING",
                execution={
                    "requested_volume": command.order.volume,
                    "requested_price": command.order.entry_price + 0.0001,
                    "stop_loss": command.order.stop_loss,
                    "take_profit": command.order.take_profit,
                },
            ),
            command,
        )


def test_cli_distinguishes_postcommit_evidence_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    committed = False

    async def fake_execute(_args: object) -> dict[str, object]:
        nonlocal committed
        committed = True
        return {
            "canary_id": "d0-cli-proof",
            "command_id": "11111111-1111-4111-8111-111111111111",
            "window_state": "ARMED",
        }

    def fail_write(_path: Path, _manifest: dict[str, object]) -> None:
        raise PermissionError("simulated evidence failure")

    async def fake_containment(_args: object) -> str:
        return "KILL_SWITCH_REENGAGED"

    monkeypatch.setattr(canary_cli, "execute", fake_execute)
    monkeypatch.setattr(canary_cli, "_write_manifest", fail_write)
    monkeypatch.setattr(canary_cli, "_contain_postcommit_failure", fake_containment)
    rc = canary_cli.main(
        [
            "arm",
            "--canary-id",
            "d0-cli-proof",
            "--actor",
            "test",
            "--reason",
            "postcommit evidence test",
            "--expected-governance-version",
            "1",
            "--confirm",
            "ARM_ONE_ENGINEERING_DEMO_CANARY",
            "--out",
            str(tmp_path / "manifest.json"),
        ]
    )
    captured = capsys.readouterr()

    assert committed is True
    assert rc == 2
    assert "ARM_COMMITTED_EVIDENCE_WRITE_FAILED" in captured.err
    assert "manifest_sha256=sha256:" in captured.err
    assert "containment=KILL_SWITCH_REENGAGED" in captured.err
    assert "aborted" not in captured.err.lower()


def test_cli_evidence_preflight_failure_never_calls_authority(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    called = False

    async def fake_execute(_args: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    def fail_preflight(_path: Path) -> None:
        raise PermissionError("simulated preflight failure")

    monkeypatch.setattr(canary_cli, "execute", fake_execute)
    monkeypatch.setattr(canary_cli, "_preflight_manifest_path", fail_preflight)
    rc = canary_cli.main(
        [
            "arm",
            "--canary-id",
            "d0-cli-proof",
            "--actor",
            "test",
            "--reason",
            "preflight evidence test",
            "--expected-governance-version",
            "1",
            "--confirm",
            "ARM_ONE_ENGINEERING_DEMO_CANARY",
            "--out",
            str(tmp_path / "manifest.json"),
        ]
    )
    captured = capsys.readouterr()

    assert called is False
    assert rc == 1
    assert "not started" in captured.err


class _FakeRepository:
    def __init__(self, *, kill_switch_active: bool = True) -> None:
        self.executor = _executor()
        self.snapshot = _snapshot()
        self.kill_switch_active = kill_switch_active
        self.enqueued: list[ExecutionCommandV1] = []

    async def engineering_demo_canary_schema_status(self) -> dict[str, bool]:
        return {"ready": True}

    async def get_executor(self, executor_id: UUID) -> dict[str, object]:
        assert executor_id == EXECUTOR_ID
        return self.executor

    async def governance_snapshot(self, executor_id: UUID) -> SimpleNamespace:
        assert executor_id == EXECUTOR_ID
        return SimpleNamespace(execution_mode="DEMO", kill_switch_active=self.kill_switch_active)

    async def latest_snapshot(self, executor_id: UUID) -> AccountSnapshotV1:
        assert executor_id == EXECUTOR_ID
        return self.snapshot

    async def enqueue_engineering_demo_canary_command(self, command: ExecutionCommandV1) -> None:
        self.enqueued.append(command)


@pytest.mark.asyncio
async def test_authority_is_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WOLF15_ENABLE_ENGINEERING_DEMO_CANARY_ISSUANCE", raising=False)
    authority = EngineeringDemoCanaryAuthorityV1(_FakeRepository())  # type: ignore[arg-type]

    with pytest.raises(EngineeringDemoCanaryError, match="disabled"):
        await authority.issue(_request())


@pytest.mark.asyncio
async def test_authority_queues_under_engaged_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WOLF15_ENABLE_ENGINEERING_DEMO_CANARY_ISSUANCE", "true")
    monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_KEY_ID", "d0-test-key")
    repository = _FakeRepository()
    authority = EngineeringDemoCanaryAuthorityV1(repository)  # type: ignore[arg-type]

    manifest = await authority.issue(_request())

    assert manifest["demo_only"] is True
    assert len(repository.enqueued) == 1
    assert repository.enqueued[0].executor_binding.execution_mode is ExecutorMode.DEMO


@pytest.mark.asyncio
async def test_authority_refuses_issue_after_global_disarm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WOLF15_ENABLE_ENGINEERING_DEMO_CANARY_ISSUANCE", "true")
    repository = _FakeRepository(kill_switch_active=False)
    authority = EngineeringDemoCanaryAuthorityV1(repository)  # type: ignore[arg-type]

    with pytest.raises(EngineeringDemoCanaryError, match="kill switch"):
        await authority.issue(_request())
