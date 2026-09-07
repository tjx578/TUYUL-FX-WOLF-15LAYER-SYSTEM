"""Offline protocol models and real Python paths; this is not real-Redis evidence."""

from __future__ import annotations

import argparse
import base64
import copy
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from services.orchestrator.legacy_import_contract import (
    KEYS,
    MAX_BYTES,
    PACKAGE_SCHEMA,
    PROCESS_IDS,
    REQUIRED_EVIDENCE,
    ImportHoldError,
    OperationDeadlineError,
    build_import_state,
    digest,
    encoded,
    load_prepared,
    prepare_documents,
    strict_json,
    validate_package,
    validate_provenance,
)
from services.orchestrator.legacy_state_import import apply_once, reconcile_observation
from services.orchestrator.ownership import _FENCED_LEGACY_IMPORT_SCRIPT, RedisFencedOwnership
from services.orchestrator.state_manager import StateHydrationError, StateManager

NOW = datetime(2026, 9, 8, tzinfo=UTC)
OPERATION = "e5c9167d-7af3-4947-91d6-e1b952435a49"


def package() -> dict[str, Any]:
    return {
        "schema": PACKAGE_SCHEMA,
        "operation_id": OPERATION,
        "valid_until": (NOW + timedelta(hours=1)).isoformat(),
        "process_binding": dict.fromkeys(PROCESS_IDS, "00000000-0000-4000-8000-000000000001"),
        "endpoint": {"scheme": "redis", "host": "disposable.invalid", "port": 6379, "database": 0},
        "keys": KEYS.copy(),
        "legacy_source_commit": "1" * 40,
        "importer_source_commit": "4" * 40,
        "source_deployment_id": "00000000-0000-4000-8000-000000000002",
        "importer_image_digest": "sha256:" + "2" * 64,
        "archive_reference": "synthetic/legacy-archive",
        "operation_marker_path": "/protected-operation-ledger/" + OPERATION + ".attempt.json",
        "lease_ttl_seconds": 30,
        "total_timeout_seconds": 20,
        "connect_timeout_seconds": 2,
        "read_timeout_seconds": 2,
        "evidence": {
            name: {
                "locator": "synthetic-offline-fixture.json",
                "sha256": "3" * 64,
                "result": "PASS",
                "observed_at": NOW.isoformat(),
            }
            for name in REQUIRED_EVIDENCE
        },
    }


def snapshot() -> dict[str, Any]:
    values = {
        "state": {
            "source": "wolf15-orchestrator",
            "channel": "wolf15:orchestrator:commands",
            "mode": "KILL_SWITCH",
            "reason": "original reason with retained spacing  ",
            "compliance_code": "ACCOUNT_STATE_MISSING",
            "updated_at": "2026-09-05T13:48:10+00:00",
            "timestamp": 1788808169,
            "event": "HEARTBEAT",
        },
        "kill": {
            "active": True,
            "source": "wolf15-orchestrator",
            "reason": "original kill reason",
            "extra": "retained",
        },
        "heartbeat": {"producer": "wolf15-orchestrator", "ts": 1788808169.5},
    }
    return {
        name: {"type": "string", "pttl": -1, "base64": base64.b64encode(json.dumps(value, indent=2).encode()).decode()}
        for name, value in values.items()
    }


def prepared() -> tuple[bytes, bytes]:
    return prepare_documents(package(), snapshot(), now=NOW)


class ModelRedis:
    """Deterministic contract emulator. It does not execute Lua or open sockets."""

    def __init__(self, raws: dict[str, bytes]) -> None:
        self.values = {KEYS[name]: raw for name, raw in raws.items()}
        self.counter = 0
        self.calls: list[str] = []
        self.state_writes = 0
        self.published: list[bytes] = []
        self.before_import: Any = None
        self.lose_reply = False
        self.fail_release = False
        self.server_time_ms = int(NOW.timestamp() * 1000)
        self.bad_type: str | None = None
        self.expiring: str | None = None

    def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    def close(self) -> None:
        pass

    def mget(self, keys: list[str]) -> list[bytes | None]:
        return [self.get(key) for key in keys]

    def eval(self, script: str, count: int, *items: Any) -> Any:
        keys, args = list(items[:count]), list(items[count:])
        self.calls.append(script.splitlines()[1])
        if "lease:acquire:v1" in script:
            if keys[0] in self.values:
                return ""
            self.counter += 1
            value = f"{args[0]}|{self.counter}".encode()
            self.values[keys[0]] = value
            return value
        if "lease:release:v1" in script:
            if self.fail_release:
                raise TimeoutError
            if self.get(keys[0]) == args[0].encode():
                del self.values[keys[0]]
                return 1
            return 0
        if "fenced-legacy-import:v1" in script:
            if self.before_import:
                self.before_import(self)
            if len(set(keys)) != 4:
                return -3
            if self.bad_type in keys or any(key not in self.values for key in keys):
                return -2
            if self.get(keys[0]) != args[0].encode():
                return -1
            if self.server_time_ms >= args[7]:
                return -3
            if self.expiring in keys or [self.get(key) for key in keys[1:]] != args[1:4]:
                return -2
            self.values[keys[1]] = args[4]
            self.state_writes += 1
            if self.lose_reply:
                raise TimeoutError
            return 1
        if "fenced-state-write:v1" in script:
            if self.get(keys[0]) != args[0].encode():
                return 0
            self.values[keys[1]] = args[1].encode()
            self.values[keys[2]] = args[2].encode()
            self.published.append(args[1].encode())
            return 1
        raise AssertionError("unexpected modeled command")


def backend() -> tuple[ModelRedis, bytes, bytes, dict[str, bytes]]:
    archive, manifest = prepared()
    _, raws = load_prepared(manifest, archive, now=NOW)
    return ModelRedis(raws), archive, manifest, raws


def test_preparation_preserves_exact_noncanonical_raw_bytes() -> None:
    archive, manifest = prepared()
    p, raws = load_prepared(manifest, archive, now=NOW)
    assert p["operation_id"] == OPERATION
    assert b"\n" in raws["state"]
    assert strict_json(raws["state"])["reason"].endswith("  ")
    assert strict_json(raws["kill"])["extra"] == "retained"
    assert digest(archive) == strict_json(manifest)["archive_sha256"]


@pytest.mark.parametrize("field", sorted(REQUIRED_EVIDENCE))
def test_missing_runtime_package_gate_fails_before_import(field: str) -> None:
    p = package()
    del p["evidence"][field]
    with pytest.raises(ImportHoldError):
        prepare_documents(p, snapshot(), now=NOW)


@pytest.mark.parametrize("change", ["unknown", "duplicate", "normal", "v2", "bool_timestamp", "nan", "expired_key"])
def test_legacy_rejection(change: str) -> None:
    s = snapshot()
    raw = base64.b64decode(s["state"]["base64"])
    value = strict_json(raw)
    if change == "unknown":
        value["unrecognized"] = True
    elif change == "duplicate":
        raw = raw.replace(b'"event": "HEARTBEAT"', b'"event": "HEARTBEAT", "event": "OTHER"')
    elif change == "normal":
        value["mode"] = "NORMAL"
    elif change == "v2":
        value["schema"] = "wolf15.orchestrator.state/v2"
    elif change == "bool_timestamp":
        value["timestamp"] = True
    elif change == "nan":
        raw = raw.replace(b"1788808169", b"NaN")
    elif change == "expired_key":
        s["state"]["pttl"] = 100
    if change not in {"duplicate", "nan"}:
        raw = encoded(value)
    s["state"]["base64"] = base64.b64encode(raw).decode()
    with pytest.raises(ImportHoldError):
        prepare_documents(package(), s, now=NOW)


@pytest.mark.parametrize("change", ["expired", "namespace", "lease_short", "evidence_failed", "endpoint_dsn"])
def test_package_rejects_invalid_binding_and_limits(change: str) -> None:
    p = package()
    if change == "expired":
        p["valid_until"] = NOW.isoformat()
    elif change == "namespace":
        p["keys"]["state"] = "other:state"
    elif change == "lease_short":
        p["lease_ttl_seconds"] = p["total_timeout_seconds"]
    elif change == "evidence_failed":
        p["evidence"]["old_writers_stopped"]["result"] = "DECLARED"
    else:
        p["endpoint"]["host"] = "redis://user:secret@host"
    with pytest.raises(ImportHoldError):
        validate_package(p, now=NOW)


def test_apply_one_set_keeps_kill_heartbeat_and_real_fence() -> None:
    client, archive, manifest, raws = backend()
    result = apply_once(client, manifest, archive, now=NOW)
    assert result["status"] == "COMMITTED"
    assert result["lease_release"] == "RELEASED"
    assert result["import_attempts"] == client.state_writes == 1
    assert client.get(KEYS["lease"]) is None
    assert client.get(KEYS["kill"]) == raws["kill"]
    assert client.get(KEYS["heartbeat"]) == raws["heartbeat"]
    assert client.published == []
    state = strict_json(client.get(KEYS["state"]))
    assert state["owner_id"] == "legacy-import-" + OPERATION
    assert state["fence_generation"] == client.counter == 1
    assert state["legacy_import"]["old_state_sha256"] == digest(raws["state"])
    for field in ("mode", "reason", "compliance_code", "updated_at"):
        assert state[field] == strict_json(raws["state"])[field]


@pytest.mark.parametrize("conflict", ["state", "kill", "heartbeat", "new_owner", "wrong_type", "ttl", "deadline"])
def test_cas_conflicts_do_not_overwrite_intervening_state(conflict: str) -> None:
    client, archive, manifest, _ = backend()

    def change(redis: ModelRedis) -> None:
        if conflict in {"state", "kill", "heartbeat"}:
            redis.values[KEYS[conflict]] = b"intervening bytes"
        elif conflict == "new_owner":
            redis.values[KEYS["lease"]] = b"new-owner|9"
        elif conflict == "wrong_type":
            redis.bad_type = KEYS["state"]
        elif conflict == "ttl":
            redis.expiring = KEYS["state"]
        else:
            redis.server_time_ms += 3600000

    client.before_import = change
    result = apply_once(client, manifest, archive, now=NOW)
    assert result["status"] == "HOLD"
    assert client.state_writes == 0
    if conflict in {"state", "kill", "heartbeat"}:
        assert client.get(KEYS[conflict]) == b"intervening bytes"
    if conflict == "new_owner":
        assert client.get(KEYS["lease"]) == b"new-owner|9"


def test_reply_loss_is_ambiguous_and_offline_reconciliation_does_not_retry() -> None:
    client, archive, manifest, _ = backend()
    client.lose_reply = True
    result = apply_once(client, manifest, archive, now=NOW)
    assert result["status"] == "AMBIGUOUS"
    assert client.state_writes == 1
    observation = client.get(KEYS["state"])
    assert reconcile_observation(manifest, archive, observation)["status"] == "COMMITTED_PROVENANCE_OBSERVED"
    assert apply_once(client, manifest, archive, now=NOW)["reason"] == "FRESH_BYTES_MISMATCH"
    assert client.state_writes == 1


def test_archive_tamper_causes_zero_backend_calls() -> None:
    client, archive, manifest, _ = backend()
    with pytest.raises(ImportHoldError):
        apply_once(client, manifest, archive + b" ", now=NOW)
    assert client.calls == []


def test_release_failure_does_not_hide_committed_result() -> None:
    client, archive, manifest, _ = backend()
    client.fail_release = True
    result = apply_once(client, manifest, archive, now=NOW)
    assert result["status"] == "COMMITTED" and result["lease_release"] == "UNKNOWN"
    assert client.state_writes == 1


def test_successor_full_start_shutdown_and_later_publication_retain_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    client, archive, manifest, _ = backend()
    assert apply_once(client, manifest, archive, now=NOW)["status"] == "COMMITTED"
    original = strict_json(client.get(KEYS["state"]))["legacy_import"]
    owner = RedisFencedOwnership(
        client, owner_id="real-successor", lease_key=KEYS["lease"], generation_key=KEYS["generation"], ttl_seconds=30
    )
    manager = StateManager(redis_client=client, ownership=owner)  # type: ignore[arg-type]
    monkeypatch.setattr(manager, "start_listener", lambda: None)

    def stop() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        manager.run_forever(on_started=stop)
    terminal = strict_json(client.get(KEYS["state"]))
    assert terminal["event"] == "SHUTDOWN"
    assert terminal["legacy_import"] == original
    assert terminal["fence_generation"] == 2 and terminal["state_revision"] == 3
    assert (
        reconcile_observation(manifest, archive, client.get(KEYS["state"]))["status"] == "COMMITTED_PROVENANCE_OBSERVED"
    )
    later_owner = RedisFencedOwnership(
        client, owner_id="later-successor", lease_key=KEYS["lease"], generation_key=KEYS["generation"], ttl_seconds=30
    )
    assert later_owner.acquire()
    later = StateManager(redis_client=client, ownership=later_owner)  # type: ignore[arg-type]
    assert later.hydrate_committed_state() is True
    later.publish_state("MODE_CHANGED")
    later.publish_state("HEARTBEAT")
    assert strict_json(client.get(KEYS["state"]))["legacy_import"] == original


@pytest.mark.parametrize("value", [None, {}, {"schema": "forged"}])
def test_malformed_provenance_fails_full_run_before_state_write(value: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, archive, manifest, _ = backend()
    apply_once(client, manifest, archive, now=NOW)
    state = strict_json(client.get(KEYS["state"]))
    state["legacy_import"] = value
    client.values[KEYS["state"]] = encoded(state)
    before = client.values.copy()
    owner = RedisFencedOwnership(
        client, owner_id="successor", lease_key=KEYS["lease"], generation_key=KEYS["generation"], ttl_seconds=30
    )
    manager = StateManager(redis_client=client, ownership=owner)  # type: ignore[arg-type]
    monkeypatch.setattr(manager, "start_listener", lambda: pytest.fail("must reject before listener"))
    with pytest.raises(StateHydrationError):
        manager.run_forever()
    assert client.values == before and client.published == []
    assert not manager._supervisor.is_ready()  # noqa: SLF001


def test_mutated_in_memory_provenance_rejected_before_publication() -> None:
    client, archive, manifest, _ = backend()
    apply_once(client, manifest, archive, now=NOW)
    owner = RedisFencedOwnership(
        client, owner_id="successor", lease_key=KEYS["lease"], generation_key=KEYS["generation"], ttl_seconds=30
    )
    assert owner.acquire()
    manager = StateManager(redis_client=client, ownership=owner)  # type: ignore[arg-type]
    manager.hydrate_committed_state()
    manager._legacy_import["archive_sha256"] = "bad"  # noqa: SLF001
    before = client.values.copy()
    with pytest.raises(ImportHoldError):
        manager.publish_state("HEARTBEAT")
    assert client.values == before


def test_provenance_cannot_counterfeit_future_generation() -> None:
    _, archive, manifest, raws = backend()
    state = strict_json(
        build_import_state(
            package(), raws, archive_sha256=digest(archive), owner="legacy-import-" + OPERATION, generation=4, now=NOW
        )
    )
    with pytest.raises(ImportHoldError):
        validate_provenance(state["legacy_import"], owner="successor", generation=3)
    changed = copy.deepcopy(state)
    changed["legacy_import"]["operation_id"] = "00000000-0000-4000-8000-000000000004"
    assert reconcile_observation(manifest, archive, encoded(changed))["status"] == "UNKNOWN"


def test_lua_source_has_one_final_mutation_and_no_publication() -> None:
    # Source assertion only, not Lua or Redis execution evidence.
    commands = [line.strip() for line in _FENCED_LEGACY_IMPORT_SCRIPT.splitlines() if "redis.call(" in line]
    mutations = [line for line in commands if "'SET'" in line or "'DEL'" in line or "'PUBLISH'" in line]
    assert mutations == ["redis.call('SET', KEYS[2], ARGV[5])"]
    assert commands[-1] == mutations[0]


def test_windows_protected_archive_fails_closed(tmp_path: Path) -> None:
    from services.orchestrator.legacy_import_cli import protected_write

    if os.name == "posix":
        tmp_path.chmod(0o700)
        path = tmp_path / "archive.json"
        protected_write(path, b"raw")
        assert path.stat().st_mode & 0o777 == 0o600
    else:
        with pytest.raises(ImportHoldError, match="PROTECTED_ARCHIVE_REQUIRES_POSIX"):
            protected_write(tmp_path / "archive.json", b"raw")
        assert not (tmp_path / "archive.json").exists()


def test_endpoint_and_process_validation_never_returns_synthetic_secret_on_error() -> None:
    from services.orchestrator.legacy_import_cli import credential_in_memory

    p = package()
    env = {**p["process_binding"], "LOCAL_REFERENCE": "redis://auditor:SYNTHETIC_SENTINEL@disposable.invalid:6379/0"}
    assert credential_in_memory(p, "LOCAL_REFERENCE", env) == env["LOCAL_REFERENCE"]
    for change in ("endpoint", "process", "missing", "query"):
        invalid = dict(env)
        if change == "endpoint":
            invalid["LOCAL_REFERENCE"] = invalid["LOCAL_REFERENCE"].replace("disposable.invalid", "other.invalid")
        elif change == "process":
            invalid[PROCESS_IDS[0]] = "mismatch"
        elif change == "missing":
            invalid.pop("LOCAL_REFERENCE")
        else:
            invalid["LOCAL_REFERENCE"] += "?socket_timeout=999"
        with pytest.raises(ImportHoldError) as caught:
            credential_in_memory(p, "LOCAL_REFERENCE", invalid)
        assert "SYNTHETIC_SENTINEL" not in str(caught.value)


def test_cli_prepare_is_dry_offline_and_hash_checks_gate_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.orchestrator import legacy_import_cli as cli

    class FixedTime:
        @staticmethod
        def now(_tz: Any = None) -> datetime:
            return NOW

    monkeypatch.setattr(cli, "datetime", FixedTime)
    monkeypatch.setattr(cli, "connect", lambda *_: pytest.fail("dry preparation cannot connect"))
    evidence = tmp_path / "operator-evidence.json"
    evidence.write_bytes(b'{"fixture":"synthetic-only"}')
    p = package()
    for item in p["evidence"].values():
        item.update(locator=str(evidence), sha256=digest(evidence.read_bytes()))
    package_file, snapshot_file = tmp_path / "package.json", tmp_path / "snapshot.json"
    package_file.write_bytes(encoded(p))
    snapshot_file.write_bytes(encoded(snapshot()))
    args = argparse.Namespace(
        command="prepare",
        package=package_file,
        snapshot=snapshot_file,
        write_archive=False,
        archive=None,
        manifest=None,
    )
    before = list(tmp_path.iterdir())
    assert cli.execute(args)["status"] == "DRY_PREPARED_NO_WRITES"
    assert list(tmp_path.iterdir()) == before
    evidence.write_bytes(b"changed")
    with pytest.raises(ImportHoldError, match="PACKAGE_EVIDENCE_HASH_MISMATCH"):
        cli.execute(args)


@pytest.mark.parametrize("case", ["dry", "success", "attempt_write_failure", "result_write_failure", "wrong_binding"])
def test_cli_apply_boundaries_with_explicit_fake_protected_store(
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.orchestrator import legacy_import_cli as cli
    from services.orchestrator import legacy_state_import as importer

    class FixedTime:
        @staticmethod
        def now(_tz: Any = None) -> datetime:
            return NOW

    @contextmanager
    def fake_parent(_path: Path):
        yield None

    client, archive, manifest, _ = backend()
    manifest_path, archive_path, receipt_path = (tmp_path / name for name in ("manifest", "archive", "receipt"))
    files = {manifest_path: manifest, archive_path: archive}
    connections: list[bool] = []

    def fake_write(path: Path, value: bytes) -> None:
        if path in files:
            raise FileExistsError
        if (case == "attempt_write_failure" and path.suffix == ".json") or (
            case == "result_write_failure" and path == receipt_path
        ):
            raise OSError("SYNTHETIC_SENTINEL_MUST_NOT_ESCAPE")
        files[path] = value

    monkeypatch.setattr(cli, "datetime", FixedTime)
    monkeypatch.setattr(importer, "datetime", FixedTime)
    monkeypatch.setattr(cli, "protected_parent", fake_parent)
    monkeypatch.setattr(cli, "protected_read", lambda path: files[path])
    monkeypatch.setattr(cli, "protected_write", fake_write)
    monkeypatch.setattr(cli, "verify_evidence", lambda _: None)  # separate real file/hash test above
    monkeypatch.setattr(cli, "operation_deadline", fake_parent)  # Windows does not claim real POSIX signal evidence
    monkeypatch.setattr(cli, "connect", lambda *_: connections.append(True) or client)
    for key, value in package()["process_binding"].items():
        monkeypatch.setenv(key, "wrong" if case == "wrong_binding" and key == PROCESS_IDS[0] else value)
    monkeypatch.setenv("LOCAL_REFERENCE", "redis://auditor:SYNTHETIC_SENTINEL@disposable.invalid:6379/0")
    args = argparse.Namespace(
        command="apply",
        manifest=manifest_path,
        archive=archive_path,
        receipt=receipt_path,
        credential_env="LOCAL_REFERENCE",
        enable_apply=case != "dry",
    )
    if case == "attempt_write_failure":
        with pytest.raises(OSError):
            cli.execute(args)
        assert not connections
    elif case == "wrong_binding":
        with pytest.raises(ImportHoldError):
            cli.execute(args)
        assert not connections
    else:
        result = cli.execute(args)
        if case == "dry":
            assert result["status"] == "DRY_APPLY_VALIDATED_NO_CONNECTION" and not connections
        else:
            assert len(connections) == 1 and client.state_writes == 1
            if case == "result_write_failure":
                assert result["status"] == "RESULT_PERSISTENCE_FAILED" and result["observed_status"] == "COMMITTED"
            else:
                assert result["status"] == "COMMITTED" and receipt_path in files
            assert Path(package()["operation_marker_path"]) in files


def test_cli_unexpected_exception_redacts_backend_detail(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    from services.orchestrator import legacy_import_cli as cli

    def fail(_args: Any) -> Any:
        raise OSError("redis://user:SYNTHETIC_SENTINEL@disposable.invalid")

    monkeypatch.setattr(cli, "execute", fail)
    assert cli.main(["apply", "--archive", "unused", "--manifest", "unused"]) == 3
    output = capsys.readouterr().out
    assert "SYNTHETIC_SENTINEL" not in output and "LOCAL_IO_OR_PACKAGE_FAILURE" in output


@pytest.mark.parametrize("stage", ["acquire_before", "acquire_after", "cas_before", "cas_after"])
def test_deadline_during_redis_call_forbids_all_followup_calls(stage: str) -> None:
    client, archive, manifest, raws = backend()
    original_eval = client.eval
    observed: list[str] = []

    def inject(script: str, count: int, *args: Any) -> Any:
        kind = "acquire" if "lease:acquire:v1" in script else "cas" if "fenced-legacy-import:v1" in script else "other"
        observed.append(kind)
        if stage.startswith(kind):
            if stage.endswith("after"):
                original_eval(script, count, *args)
            raise OperationDeadlineError
        return original_eval(script, count, *args)

    client.eval = inject  # type: ignore[method-assign]
    result = apply_once(client, manifest, archive, now=NOW)
    assert result["status"] == "AMBIGUOUS"
    assert result["reason"] == "DEADLINE_NO_FURTHER_REDIS_CALLS"
    assert result["lease_release"] == "NOT_ATTEMPTED_DEADLINE_LEASE_TTL"
    assert observed == (["acquire"] if stage.startswith("acquire") else ["acquire", "cas"])
    assert client.get(KEYS["kill"]) == raws["kill"] and client.get(KEYS["heartbeat"]) == raws["heartbeat"]
    assert client.state_writes == int(stage == "cas_after")


def test_single_connection_wrapper_blocks_reconnect_after_failure() -> None:
    from types import SimpleNamespace

    from services.orchestrator.legacy_import_cli import SingleConnection

    calls: list[str] = []

    def fail(*_args: Any) -> None:
        calls.append("network")
        raise TimeoutError

    raw_client = SimpleNamespace(
        connection=SimpleNamespace(_sock=object()), eval=fail, close=lambda: calls.append("close")
    )
    wrapped = SingleConnection(raw_client)
    with pytest.raises(TimeoutError):
        wrapped.eval("acquire")
    with pytest.raises(ImportHoldError, match="RECONNECT_FORBIDDEN"):
        wrapped.eval("release")
    wrapped.close()
    assert calls == ["network", "close"]


@pytest.mark.parametrize("extra_bytes", [-1, 0, 1])
def test_ordinary_v2_hydration_size_boundary(extra_bytes: int) -> None:
    client, archive, manifest, _ = backend()
    apply_once(client, manifest, archive, now=NOW)
    state = strict_json(client.get(KEYS["state"]))
    del state["legacy_import"]
    state["details"] = ""
    state["details"] = "x" * (MAX_BYTES - len(encoded(state)) + extra_bytes)
    raw = encoded(state)
    assert len(raw) == MAX_BYTES + extra_bytes
    client.values[KEYS["state"]] = raw
    owner = RedisFencedOwnership(
        client, owner_id="normal-successor", lease_key=KEYS["lease"], generation_key=KEYS["generation"], ttl_seconds=30
    )
    assert owner.acquire()
    manager = StateManager(redis_client=client, ownership=owner)  # type: ignore[arg-type]
    if extra_bytes > 0:
        with pytest.raises(StateHydrationError):
            manager.hydrate_committed_state()
    else:
        assert manager.hydrate_committed_state() is True
        assert manager._legacy_import is None  # noqa: SLF001
    assert client.get(KEYS["state"]) == raw


@pytest.mark.parametrize("malformation", ["duplicate", "nonfinite", "overflow", "negative_overflow"])
def test_ordinary_v2_rejects_duplicate_and_nonfinite_json(malformation: str) -> None:
    client, archive, manifest, _ = backend()
    apply_once(client, manifest, archive, now=NOW)
    state = strict_json(client.get(KEYS["state"]))
    del state["legacy_import"]
    raw = encoded(state)
    suffix = {
        "duplicate": b',"reason":"duplicate"}',
        "nonfinite": b',"details":NaN}',
        "overflow": b',"details":{"nested":[{"number":1e999}]}}',
        "negative_overflow": b',"details":[{"nested":-1e999}]}',
    }[malformation]
    raw = raw[:-1] + suffix
    client.values[KEYS["state"]] = raw
    owner = RedisFencedOwnership(
        client, owner_id="normal-successor", lease_key=KEYS["lease"], generation_key=KEYS["generation"], ttl_seconds=30
    )
    assert owner.acquire()
    manager = StateManager(redis_client=client, ownership=owner)  # type: ignore[arg-type]
    with pytest.raises(StateHydrationError):
        manager.hydrate_committed_state()
    assert client.get(KEYS["state"]) == raw


@pytest.mark.parametrize("raw", [b"1e999", b"-1e999", b'{"x":[1e999]}', b'[{"a":{"b":-1e999}}]'])
def test_exponent_overflow_is_rejected_at_any_nesting(raw: bytes) -> None:
    with pytest.raises(ImportHoldError):
        strict_json(raw)
    assert strict_json(b'{"finite":[1e308,-1.5,0.125]}') == {"finite": [1e308, -1.5, 0.125]}


@pytest.mark.parametrize("path", ["", "/", "/0"])
def test_default_redis_database_zero_requires_explicit_zero_binding(path: str) -> None:
    from services.orchestrator.legacy_import_cli import credential_in_memory

    p = package()
    value = "redis://auditor:SYNTHETIC_SENTINEL@disposable.invalid:6379" + path
    env = {**p["process_binding"], "LOCAL_REFERENCE": value}
    assert credential_in_memory(p, "LOCAL_REFERENCE", env) == value
    p["endpoint"]["database"] = 1
    with pytest.raises(ImportHoldError):
        credential_in_memory(p, "LOCAL_REFERENCE", env)
    env["LOCAL_REFERENCE"] = "redis://auditor:SYNTHETIC_SENTINEL@disposable.invalid:6379/1"
    assert credential_in_memory(p, "LOCAL_REFERENCE", env) == env["LOCAL_REFERENCE"]


@pytest.mark.parametrize(
    "marker",
    [
        "relative/operation.attempt.json",
        "/ledger/../other/operation.attempt.json",
        "/ledger//operation.attempt.json",
        "/ledger/wrong-id.attempt.json",
        "//ledger/operation.attempt.json",
    ],
)
def test_marker_location_must_be_canonical_absolute_and_operation_bound(marker: str) -> None:
    p = package()
    p["operation_marker_path"] = marker
    with pytest.raises(ImportHoldError):
        prepare_documents(p, snapshot(), now=NOW)


def test_package_bound_marker_prevents_retry_after_receipt_and_archive_relocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.orchestrator import legacy_import_cli as cli

    class FixedTime:
        @staticmethod
        def now(_tz: Any = None) -> datetime:
            return NOW

    @contextmanager
    def fake_parent(_path: Path):
        yield None

    archive, manifest = prepared()
    first, relocated = tmp_path / "first", tmp_path / "relocated"
    files = {
        first / "manifest": manifest,
        first / "archive": archive,
        relocated / "manifest": manifest,
        relocated / "archive": archive,
    }
    calls: list[str] = []

    def claim(path: Path, raw: bytes) -> None:
        if path in files:
            raise FileExistsError("consumed")
        files[path] = raw

    def ambiguous_connect(*_args: Any) -> Any:
        calls.append("connect")
        raise TimeoutError("synthetic ambiguous connect")

    monkeypatch.setattr(cli, "datetime", FixedTime)
    monkeypatch.setattr(cli, "protected_read", lambda path: files[path])
    monkeypatch.setattr(cli, "protected_parent", fake_parent)
    monkeypatch.setattr(cli, "operation_deadline", fake_parent)
    monkeypatch.setattr(cli, "protected_write", claim)
    monkeypatch.setattr(cli, "verify_evidence", lambda _: None)
    monkeypatch.setattr(cli, "connect", ambiguous_connect)
    for key, value in package()["process_binding"].items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("LOCAL_REFERENCE", "redis://auditor:SYNTHETIC_SENTINEL@disposable.invalid:6379")

    def args(parent: Path) -> argparse.Namespace:
        return argparse.Namespace(
            command="apply",
            manifest=parent / "manifest",
            archive=parent / "archive",
            receipt=parent / "receipt",
            credential_env="LOCAL_REFERENCE",
            enable_apply=True,
        )

    assert cli.execute(args(first))["status"] == "AMBIGUOUS"
    marker = Path(package()["operation_marker_path"])
    original_marker = files[marker]
    with pytest.raises(FileExistsError):
        cli.execute(args(relocated))
    assert calls == ["connect"] and files[marker] == original_marker
    assert relocated / "receipt" not in files


@pytest.mark.parametrize("alias_target", ["marker", "archive", "manifest"])
def test_receipt_destination_alias_holds_before_claim_and_connection(
    alias_target: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.orchestrator import legacy_import_cli as cli

    class FixedTime:
        @staticmethod
        def now(_tz: Any = None) -> datetime:
            return NOW

    archive, manifest = prepared()
    marker = Path(package()["operation_marker_path"])
    archive_path, manifest_path = tmp_path / "archive", tmp_path / "manifest"
    files = {archive_path: archive, manifest_path: manifest}
    destinations = {
        "marker": marker.parent / "child" / ".." / marker.name,
        "archive": archive_path,
        "manifest": manifest_path,
    }
    monkeypatch.setattr(cli, "datetime", FixedTime)
    monkeypatch.setattr(cli, "protected_read", lambda path: files[path])
    monkeypatch.setattr(cli, "verify_evidence", lambda _: None)
    monkeypatch.setattr(cli, "protected_write", lambda *_: pytest.fail("alias cannot consume an attempt"))
    monkeypatch.setattr(cli, "connect", lambda *_: pytest.fail("alias cannot connect"))
    args = argparse.Namespace(
        command="apply",
        manifest=manifest_path,
        archive=archive_path,
        receipt=destinations[alias_target],
        credential_env="LOCAL_REFERENCE",
        enable_apply=True,
    )
    with pytest.raises(ImportHoldError, match="IMPORT_DESTINATION_ALIAS_REJECTED"):
        cli.execute(args)
    assert marker not in files


def test_rebinding_marker_path_cannot_reuse_existing_archive() -> None:
    archive, manifest = prepared()
    changed = strict_json(manifest)
    changed["package"]["operation_marker_path"] = "/different-ledger/" + OPERATION + ".attempt.json"
    with pytest.raises(ImportHoldError):
        load_prepared(encoded(changed), archive, now=NOW)
