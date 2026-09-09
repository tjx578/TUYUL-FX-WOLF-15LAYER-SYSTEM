"""Read-only auditor for one C3 risk-authorized MT5 SHADOW command."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contracts.mt5_execution_protocol import SIGNED_WIRE_VERSION
from contracts.mt5_operator_shadow import OperatorShadowManifest
from execution.mt5_command_repository import MT5CommandRepository
from execution.mt5_risk_command_producer import MT5RiskCommandProducer
from storage.postgres_client import pg_client


class C3ShadowAuditError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    return parser


def load_manifest(path: Path) -> OperatorShadowManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return OperatorShadowManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise C3ShadowAuditError("C3_MANIFEST_INVALID", "manifest cannot be loaded") from exc


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise C3ShadowAuditError("C3_DATABASE_JSON_INVALID", f"{field} is not an object")
    return dict(value)


async def _wait_for_terminal(
    repository: MT5CommandRepository,
    manifest: OperatorShadowManifest,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        status = await repository.command_status(
            executor_id=manifest.executor_id,
            command_id=manifest.command_id,
        )
        if bool(status.get("terminal")):
            return status
        if time.monotonic() >= deadline:
            raise C3ShadowAuditError("C3_COMMAND_TIMEOUT", "command did not reach a terminal state")
        await asyncio.sleep(poll_seconds)


async def audit(
    manifest: OperatorShadowManifest,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, object]:
    await pg_client.initialize()
    try:
        if not pg_client.is_available:
            raise C3ShadowAuditError("C3_DATABASE_UNAVAILABLE", "PostgreSQL is unavailable")
        repository = MT5CommandRepository(pg=pg_client)
        signed_wire = await repository.signed_wire_schema_status()
        command_schema = await MT5RiskCommandProducer(pg=pg_client).schema_status()
        if not signed_wire.get("ready") or not command_schema.get("ready"):
            raise C3ShadowAuditError("C3_SCHEMA_NOT_READY", "signed command schema is incomplete")

        governance = await repository.governance_snapshot(manifest.executor_id)
        if not governance.kill_switch_active:
            raise C3ShadowAuditError("C3_KILL_SWITCH_DISENGAGED", "kill switch is not engaged")
        if governance.execution_mode != "SHADOW":
            raise C3ShadowAuditError("C3_EXECUTOR_NOT_SHADOW", "executor is not SHADOW")

        status = await _wait_for_terminal(
            repository,
            manifest,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        if status.get("command_state") not in {"SHADOW_COMPLETED", "SHADOW_REJECTED"}:
            raise C3ShadowAuditError("C3_TERMINAL_STATE_INVALID", "command did not terminate as SHADOW")

        row = await pg_client.fetchrow(
            """
            SELECT c.source_event, c.source_signal_id, c.source_signal_hash,
                   c.risk_reservation_id, c.risk_snapshot_id, c.action,
                   c.payload, c.payload_hash, c.wire_format, c.signed_payload_sha256,
                   c.state AS command_state, c.terminal_at,
                   r.tradeplan_id, r.executor_id, r.canonical_symbol, r.broker_symbol,
                   r.account_snapshot_id, r.signal_id, r.signal_hash,
                   r.state AS reservation_state, r.command_id AS reservation_command_id,
                   o.outbox_id, o.status AS outbox_status,
                   (SELECT count(*) FROM execution_reports er WHERE er.command_id = c.command_id) AS report_count,
                   (SELECT count(*) FROM broker_entities be WHERE be.command_id = c.command_id) AS broker_entities
            FROM execution_commands c
            JOIN strategy_5scr_risk_reservations r ON r.reservation_id = c.risk_reservation_id
            JOIN strategy_5scr_final_signal_outbox o ON o.reservation_id = r.reservation_id
            WHERE c.command_id = $1::uuid AND c.executor_id = $2::uuid
            """,
            str(manifest.command_id),
            str(manifest.executor_id),
        )
        if row is None:
            raise C3ShadowAuditError("C3_COMMAND_MISSING", "command lineage is missing")
        exact = {
            "tradeplan_id": (str(row["tradeplan_id"]), manifest.tradeplan_id),
            "executor_id": (str(row["executor_id"]), str(manifest.executor_id)),
            "canonical_symbol": (str(row["canonical_symbol"]), manifest.canonical_symbol),
            "broker_symbol": (str(row["broker_symbol"]), manifest.broker_symbol),
            "risk_reservation_id": (str(row["risk_reservation_id"]), str(manifest.risk_reservation_id)),
            "risk_snapshot_id": (str(row["risk_snapshot_id"]), manifest.risk_snapshot_id),
            "final_signal_id": (str(row["signal_id"]), manifest.final_signal_id),
            "final_signal_hash": (str(row["signal_hash"]), manifest.final_signal_hash),
            "outbox_id": (str(row["outbox_id"]), str(manifest.outbox_id)),
            "command_id": (str(row["reservation_command_id"]), str(manifest.command_id)),
        }
        drift = sorted(name for name, values in exact.items() if values[0] != values[1])
        if drift:
            raise C3ShadowAuditError("C3_LINEAGE_DRIFT", "lineage drift: " + ",".join(drift))
        if (
            row["source_event"] != "signal_json"
            or row["source_signal_id"] != manifest.final_signal_id
            or row["source_signal_hash"] != manifest.final_signal_hash
            or row["action"] != "PLACE_MARKET"
            or row["reservation_state"] != "CONSUMED"
            or row["outbox_status"] != "PUBLISHED"
            or row["wire_format"] != SIGNED_WIRE_VERSION
            or row["signed_payload_sha256"] != row["payload_hash"]
            or row["terminal_at"] is None
        ):
            raise C3ShadowAuditError("C3_AUTHORITY_STATE_INVALID", "durable authority state is incomplete")

        command = _mapping(row["payload"], "command payload")
        binding = _mapping(command.get("executor_binding"), "executor_binding")
        source = _mapping(command.get("source"), "source")
        guards = _mapping(command.get("guards"), "guards")
        if (
            binding.get("execution_mode") != "SHADOW"
            or source.get("source_event") != "signal_json"
            or source.get("source_signal_id") != manifest.final_signal_id
            or source.get("source_signal_hash") != manifest.final_signal_hash
            or guards.get("risk_reservation_id") != str(manifest.risk_reservation_id)
            or guards.get("risk_snapshot_id") != manifest.risk_snapshot_id
        ):
            raise C3ShadowAuditError("C3_COMMAND_BINDING_INVALID", "command payload binding is incomplete")

        reports = await pg_client.fetch(
            "SELECT state, payload FROM execution_reports WHERE command_id = $1::uuid ORDER BY sequence",
            str(manifest.command_id),
        )
        if len(reports) != 1 or int(row["report_count"]) != 1:
            raise C3ShadowAuditError("C3_REPORT_CARDINALITY_INVALID", "exactly one report is required")
        report_state = str(reports[0]["state"])
        report = _mapping(reports[0]["payload"], "report payload")
        execution = _mapping(report.get("execution"), "report execution")
        broker = _mapping(report.get("broker"), "report broker")
        if report_state not in {"WOULD_EXECUTE", "WOULD_REJECT"}:
            raise C3ShadowAuditError("C3_REPORT_STATE_INVALID", "report is not a SHADOW result")
        expected_command_state = "SHADOW_COMPLETED" if report_state == "WOULD_EXECUTE" else "SHADOW_REJECTED"
        if str(row["command_state"]) != expected_command_state:
            raise C3ShadowAuditError("C3_REPORT_STATE_MISMATCH", "report and terminal command state differ")
        reason_code = report.get("reason_code")
        if (
            report.get("command_id") != str(manifest.command_id)
            or report.get("executor_id") != str(manifest.executor_id)
            or report.get("state") != report_state
            or report.get("request_hash") != row["payload_hash"]
            or not isinstance(reason_code, str)
            or not reason_code
            or (report_state == "WOULD_EXECUTE" and reason_code != "SHADOW_PREFLIGHT_PASSED")
        ):
            raise C3ShadowAuditError("C3_REPORT_BINDING_INVALID", "report binding or reason is invalid")
        if (
            execution.get("filled_volume") not in {None, 0}
            or broker.get("order_ticket") is not None
            or broker.get("deal_ticket") is not None
            or broker.get("position_id") is not None
            or int(row["broker_entities"]) != 0
        ):
            raise C3ShadowAuditError("C3_BROKER_EFFECT_DETECTED", "SHADOW command has a broker effect")

        final_snapshot = await repository.latest_snapshot(manifest.executor_id)
        if final_snapshot is None:
            raise C3ShadowAuditError("C3_FINAL_SNAPSHOT_MISSING", "final account snapshot is missing")
        if final_snapshot.open_positions:
            raise C3ShadowAuditError("C3_FINAL_POSITIONS_NONZERO", "final account snapshot contains positions")

        return {
            "schema_version": "wolf15.mt5.operator-shadow-audit.v1",
            "status": "PASS",
            "operator_run_id": manifest.operator_run_id,
            "command_id": str(manifest.command_id),
            "risk_reservation_id": str(manifest.risk_reservation_id),
            "canonical_symbol": manifest.canonical_symbol,
            "broker_symbol": manifest.broker_symbol,
            "command_state": str(row["command_state"]),
            "report_state": report_state,
            "kill_switch_active": True,
            "execution_mode": "SHADOW",
            "filled_volume": 0,
            "broker_order_id": None,
            "broker_deal_id": None,
            "broker_position_id": None,
            "broker_entities": 0,
            "final_open_positions": 0,
            "audited_at_utc": datetime.now(UTC).isoformat(),
        }
    finally:
        await pg_client.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0 or args.poll_seconds <= 0:
        parser.error("timeout and poll values must be positive")
    try:
        manifest = load_manifest(args.manifest)
        result = asyncio.run(
            audit(
                manifest,
                timeout_seconds=args.timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
        )
    except Exception as exc:
        reason_code = str(getattr(exc, "reason_code", type(exc).__name__))
        print(json.dumps({"status": "FAIL", "reason_code": reason_code}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
