"""Unit contracts for the read-only MT5 SHADOW matrix auditor."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

import scripts.audit_mt5_shadow_matrix as matrix


def _manifest_payload(*, phase: str = "A1") -> dict[str, object]:
    pairs = matrix.load_symbol_universe()
    selected = pairs[:1] if phase == "A1" else pairs
    return {
        "schema_version": matrix.MANIFEST_VERSION,
        "run_id": "audit-20260803-a1",
        "phase": phase,
        "symbol_universe": matrix.REQUIRED_UNIVERSE,
        "executor_id": "11111111-1111-4111-8111-111111111111",
        "broker_server": "XMGlobal-MT5 10",
        "expected_ea_version": matrix.EXPECTED_EA_VERSION,
        "expected_protocol_version": matrix.PROTOCOL_VERSION,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "commands": [
            {
                "canonical_symbol": canonical,
                "broker_symbol": broker,
                "command_id": str(uuid5(NAMESPACE_URL, f"matrix/{canonical}")),
            }
            for canonical, broker in selected
        ],
    }


def _write_manifest(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a1_manifest_is_strict_and_contains_no_account_secret(tmp_path: Path) -> None:
    manifest = matrix.load_manifest(_write_manifest(tmp_path / "manifest.json", _manifest_payload()))

    assert manifest.phase == "A1"
    assert len(manifest.commands) == 1
    assert manifest.commands[0].canonical_symbol == "EURUSD"
    assert "account_id" not in manifest.__dataclass_fields__


def test_a2_manifest_requires_the_exact_frozen_universe(tmp_path: Path) -> None:
    manifest = matrix.load_manifest(_write_manifest(tmp_path / "manifest.json", _manifest_payload(phase="A2")))

    assert len(manifest.commands) == matrix.EXPECTED_SYMBOL_COUNT
    assert {(item.canonical_symbol, item.broker_symbol) for item in manifest.commands} == set(
        matrix.load_symbol_universe()
    )


@pytest.mark.parametrize("field", ["account_id", "executor_token", "signing_secret", "verification_key"])
def test_manifest_rejects_credentials_and_account_identifiers(tmp_path: Path, field: str) -> None:
    payload = _manifest_payload()
    payload[field] = "must-not-be-here"

    with pytest.raises(matrix.MatrixAbortError, match="keys mismatch") as raised:
        matrix.load_manifest(_write_manifest(tmp_path / "manifest.json", payload))

    assert raised.value.reason_code == "MANIFEST_KEYS_INVALID"


def test_manifest_rejects_unsafe_run_id(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["run_id"] = "../../unsafe"

    with pytest.raises(matrix.MatrixAbortError) as raised:
        matrix.load_manifest(_write_manifest(tmp_path / "manifest.json", payload))

    assert raised.value.reason_code == "RUN_ID_INVALID"


def test_manifest_rejects_duplicate_commands(tmp_path: Path) -> None:
    payload = _manifest_payload(phase="A2")
    commands = payload["commands"]
    assert isinstance(commands, list)
    commands[1] = dict(commands[0])

    with pytest.raises(matrix.MatrixAbortError) as raised:
        matrix.load_manifest(_write_manifest(tmp_path / "manifest.json", payload))

    assert raised.value.reason_code in {"COMMAND_ID_DUPLICATE", "CANONICAL_SYMBOL_DUPLICATE"}


def test_manifest_rejects_wrong_broker_alias(tmp_path: Path) -> None:
    payload = _manifest_payload()
    commands = payload["commands"]
    assert isinstance(commands, list)
    command = commands[0]
    assert isinstance(command, dict)
    command["broker_symbol"] = "EURUSD.invalid"

    with pytest.raises(matrix.MatrixAbortError) as raised:
        matrix.load_manifest(_write_manifest(tmp_path / "manifest.json", payload))

    assert raised.value.reason_code == "SYMBOL_PAIR_MISMATCH"


def test_cli_exposes_no_enqueue_or_open_position_bypass() -> None:
    parser = matrix.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}

    assert "--execute-target-required" not in options
    assert "--allow-open-positions" not in options
    assert "--expected-account-id" not in options
    assert "--manifest" in options
    assert "--out" in options


def test_source_has_no_signing_or_enqueue_authority() -> None:
    source = Path(matrix.__file__).read_text(encoding="utf-8")

    assert "sign_execution_command" not in source
    assert "enqueue_command" not in source
    assert "EXECUTOR_COMMAND_SIGNING_SECRET" not in source
    assert "risk_reservation_id" not in source
    assert '"source_event"' not in source


def test_main_writes_fail_closed_artifact_for_unexpected_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _write_manifest(tmp_path / "manifest.json", _manifest_payload())
    output_path = tmp_path / "result.json"

    async def _explode(*_args: object, **_kwargs: object) -> matrix.AuditSummary:
        raise RuntimeError("sensitive detail must not be serialized")

    monkeypatch.setattr(matrix, "audit_manifest", _explode)

    assert matrix.main(["--manifest", str(manifest_path), "--out", str(output_path)]) == 3
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["status"] == "ABORTED"
    assert result["reason_code"] == "UNEXPECTED_ERROR"
    assert result["failure_detail"] == "RuntimeError"
    assert "sensitive" not in output_path.read_text(encoding="utf-8")
