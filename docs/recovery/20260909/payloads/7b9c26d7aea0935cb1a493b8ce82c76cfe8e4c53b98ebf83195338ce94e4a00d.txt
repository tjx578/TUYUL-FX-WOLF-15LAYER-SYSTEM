"""Opt-in actual Lua campaign on disposable Redis. No production defaults.

Protected Linux files/signals are not exercised. Response loss is injected only
after Redis has returned success; this is not a real network-disconnect test.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from services.orchestrator import state_manager as state_module
from services.orchestrator.legacy_import_cli import connect
from services.orchestrator.legacy_import_contract import (
    KEYS,
    build_import_state,
    digest,
    encoded,
    load_prepared,
    prepare_documents,
    strict_json,
)
from services.orchestrator.legacy_state_import import apply_once, reconcile_observation
from services.orchestrator.ownership import LegacyImportConflictError, OwnershipLostError, RedisFencedOwnership
from tests.integration.test_orchestrator_process_recovery import disposable_redis as disposable_redis
from tests.test_orchestrator_legacy_import import package as synthetic_package
from tests.test_orchestrator_legacy_import import snapshot as synthetic_snapshot

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_PATHS = {
    "services/orchestrator/legacy_import_contract.py",
    "services/orchestrator/legacy_import_cli.py",
    "services/orchestrator/legacy_state_import.py",
    "services/orchestrator/ownership.py",
    "services/orchestrator/state_manager.py",
}
pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture(scope="module", autouse=True)
def bound_source() -> dict[str, Any]:
    if os.getenv("WOLF15_RUN_PROCESS_RECOVERY") != "1":
        pytest.skip("explicit disposable campaign opt-in required")
    path = Path(os.environ["WOLF15_IMPORT_REVIEW_RECEIPT"])
    raw = path.read_bytes()
    assert digest(raw) == os.environ["WOLF15_IMPORT_REVIEW_RECEIPT_SHA256"]
    receipt = json.loads(raw)
    assert receipt["source"]["commit"] == os.environ["WOLF15_IMPORT_PRODUCT_COMMIT"]
    assert set(receipt["source"]["product_files"]) == PRODUCT_PATHS
    assert Path(state_module.__file__).resolve() == ROOT / "services/orchestrator/state_manager.py"
    hashes = {}
    for name, info in receipt["source"]["product_files"].items():
        hashes[name] = digest((ROOT / name).read_bytes())
        assert hashes[name] == info["working_sha256"], name
    return {
        "product_commit": receipt["source"]["commit"],
        "product_sha256": hashes,
        "harness_sha256": digest(Path(__file__).read_bytes()),
        "fixture_sha256": digest((ROOT / "tests/integration/test_orchestrator_process_recovery.py").read_bytes()),
        "interpreter": {"executable": sys.executable, "version": sys.version},
        "redis_py": {"version": redis.__version__, "module_path": redis.__file__},
        "pytest_version": pytest.__version__,
    }


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _fingerprints(client: Any) -> dict[str, Any]:
    result = {}
    for name in ("state", "kill", "heartbeat"):
        key = KEYS[name]
        kind = client.type(key)
        value = client.get(key) if kind == "string" else client.lrange(key, 0, -1)
        raw = value.encode("utf-8") if isinstance(value, str) else encoded(value)
        result[name] = {"type": kind, "sha256": digest(raw)}
    return result


@contextmanager
def _case(disposable: Any, source: dict[str, Any], name: str):
    admin, port, root, meta = disposable
    now = datetime.now(UTC)
    p = synthetic_package()
    p["valid_until"] = (now + timedelta(minutes=5)).isoformat()
    p["endpoint"] = {"scheme": "redis", "host": "127.0.0.1", "port": port, "database": 0}
    for evidence in p["evidence"].values():
        evidence["observed_at"] = now.isoformat()
    archive, manifest = prepare_documents(p, synthetic_snapshot(), now=now)
    _, raws = load_prepared(manifest, archive, now=now)
    for key, value in raws.items():
        admin.set(KEYS[key], value)
    actor = connect(p, f"redis://127.0.0.1:{port}/0")
    receipt: dict[str, Any] = {
        "case": name,
        "status": "NOT_COMPLETED",
        "source": source,
        "redis": meta,
        "fixture": "SYNTHETIC_NO_PRODUCTION_DATA",
        "archive_sha256": digest(archive),
        "manifest_sha256": digest(manifest),
        "snapshot_value_sha256": {name: digest(raw) for name, raw in raws.items()},
        "notes": [],
        "production_connections": 0,
    }
    try:
        yield admin, actor, p, raws, archive, manifest, receipt
        receipt["status"] = "PASS_LOCAL_REAL_REDIS"
    finally:
        actor.close()
        receipt["actor_closed"] = True
        _write(root / "import-receipt.json", receipt)


def _owner(actor: Any, label: str, ttl: int = 30) -> RedisFencedOwnership:
    return RedisFencedOwnership(
        actor, owner_id=label, lease_key=KEYS["lease"], generation_key=KEYS["generation"], ttl_seconds=ttl
    )


def _submit(owner: RedisFencedOwnership, p: Any, raws: Any, archive: bytes) -> None:
    assert owner.identity is not None
    payload = build_import_state(
        p,
        raws,
        archive_sha256=digest(archive),
        owner=owner.identity.owner_id,
        generation=owner.identity.generation,
        now=datetime.now(UTC),
    )
    owner.fenced_legacy_import(
        state_key=KEYS["state"],
        kill_key=KEYS["kill"],
        heartbeat_key=KEYS["heartbeat"],
        old_state=raws["state"],
        old_kill=raws["kill"],
        old_heartbeat=raws["heartbeat"],
        new_state=payload,
        valid_until_epoch_ms=int(datetime.fromisoformat(p["valid_until"]).timestamp() * 1000),
    )


def test_real_import_and_successor_boot_keep_provenance(disposable_redis: Any, bound_source: Any) -> None:
    with _case(disposable_redis, bound_source, "success-and-successor") as (
        admin,
        actor,
        p,
        raws,
        archive,
        manifest,
        r,
    ):
        result = apply_once(actor, manifest, archive)
        assert result["status"] == "COMMITTED" and result["lease_release"] == "RELEASED"
        assert result["import_attempts"] == 1
        assert actor.mget([KEYS["kill"], KEYS["heartbeat"]]) == [raws["kill"], raws["heartbeat"]]
        imported_raw = admin.get(KEYS["state"]).encode()
        imported = strict_json(imported_raw)
        actor.close()
        successor_client = redis.Redis(
            host="127.0.0.1",
            port=p["endpoint"]["port"],
            db=0,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry=Retry(NoBackoff(), 0),
        )
        successor = _owner(successor_client, "successor-" + uuid4().hex)
        try:
            assert successor.acquire()
            assert successor.identity.generation > result["fence_generation"]
            manager = state_module.StateManager(redis_client=successor_client, ownership=successor)
            assert manager.hydrate_committed_state() is True
            manager.publish_state("BOOT", {"hydrated": True, "prior_state_revision": 1})
            boot_raw = admin.get(KEYS["state"]).encode()
            boot = strict_json(boot_raw)
            assert boot["legacy_import"] == imported["legacy_import"]
            assert boot["state_revision"] == 2 and boot["event"] == "BOOT"
            assert boot["mode"] == "KILL_SWITCH" and boot["updated_at"] == imported["updated_at"]
            assert reconcile_observation(manifest, archive, boot_raw)["status"] == "COMMITTED_PROVENANCE_OBSERVED"
            r.update(
                result=result,
                imported_state_sha256=digest(imported_raw),
                boot_state_sha256=digest(boot_raw),
                successor_generation=successor.identity.generation,
                kill_heartbeat_unchanged_at_import=True,
                boot_provenance_retained=True,
            )
        finally:
            try:
                successor.release()
            finally:
                successor_client.close()


def test_real_cas_byte_type_and_ttl_conflicts_preserve_intervening_values(
    disposable_redis: Any, bound_source: Any
) -> None:
    with _case(disposable_redis, bound_source, "byte-type-ttl-conflicts") as (
        admin,
        actor,
        p,
        raws,
        archive,
        _manifest,
        r,
    ):
        outcomes = []
        for name, change in [(n, c) for n in ("state", "kill", "heartbeat") for c in ("bytes", "type")] + [
            ("state", "ttl")
        ]:
            for key, value in raws.items():
                # Only explicitly owned disposable fixture keys, never production data.
                admin.delete(KEYS[key])
                admin.set(KEYS[key], value)
            owner = _owner(actor, "legacy-import-" + p["operation_id"])
            try:
                assert owner.acquire()
                if change == "bytes":
                    admin.set(KEYS[name], b"intervening-fixture-bytes")
                elif change == "type":
                    admin.delete(KEYS[name])
                    admin.rpush(KEYS[name], "intervening-fixture-list")
                else:
                    admin.pexpire(KEYS[name], 20000)
                before = _fingerprints(admin)
                ttl_before = admin.pttl(KEYS[name]) if change == "ttl" else None
                with pytest.raises(LegacyImportConflictError):
                    _submit(owner, p, raws, archive)
                assert _fingerprints(admin) == before
                ttl_after = admin.pttl(KEYS[name]) if change == "ttl" else None
                if change == "ttl":
                    assert 0 < ttl_after <= ttl_before
                outcomes.append(
                    {
                        "key": name,
                        "change": change,
                        "preserved": before,
                        "generation": owner.identity.generation,
                        "pttl_before": ttl_before,
                        "pttl_after": ttl_after,
                    }
                )
            finally:
                owner.release()
        r["conflicts"] = outcomes


def test_real_expired_and_stale_leases_cannot_import(disposable_redis: Any, bound_source: Any) -> None:
    with _case(disposable_redis, bound_source, "expired-and-stale-leases") as (
        admin,
        actor,
        p,
        raws,
        archive,
        _manifest,
        r,
    ):
        outcomes = []
        for replacement in (False, True):
            old = _owner(actor, "legacy-import-" + p["operation_id"], ttl=3)
            fresh = None
            try:
                assert old.acquire()
                old_generation = old.identity.generation
                deadline = time.monotonic() + 5
                while admin.exists(KEYS["lease"]):
                    assert time.monotonic() < deadline, "real lease expiry exceeded bound"
                    time.sleep(0.05)
                if replacement:
                    fresh = _owner(actor, "replacement-" + uuid4().hex)
                    assert fresh.acquire() and fresh.identity.generation > old_generation
                before = _fingerprints(admin)
                with pytest.raises((LegacyImportConflictError, OwnershipLostError)):
                    _submit(old, p, raws, archive)
                assert _fingerprints(admin) == before
                outcomes.append(
                    {
                        "replacement": replacement,
                        "old_generation": old_generation,
                        "new_generation": fresh.identity.generation if fresh else None,
                        "preserved": before,
                        "expiry": "REAL_3_SECOND_LEASE",
                    }
                )
            finally:
                old.release()
                if fresh is not None:
                    fresh.release()
        r["lease_cases"] = outcomes


def test_real_set_with_injected_response_loss_is_ambiguous_without_resend(
    disposable_redis: Any,
    bound_source: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _case(disposable_redis, bound_source, "real-set-injected-response-loss") as (
        admin,
        actor,
        _p,
        raws,
        archive,
        manifest,
        r,
    ):
        raw_client = actor._client  # noqa: SLF001 -- explicit driver-boundary fault injection
        original_eval = raw_client.eval
        import_calls = []

        def lose_reply(script: str, *args: Any) -> Any:
            result = original_eval(script, *args)
            if "fenced-legacy-import:v1" in script:
                import_calls.append(result)
                assert result == 1  # The actual Redis SET has completed and its reply was received.
                raise TimeoutError("SYNTHETIC_REPLY_LOSS_AFTER_REAL_SUCCESS")
            return result

        monkeypatch.setattr(raw_client, "eval", lose_reply)
        result = apply_once(actor, manifest, archive)
        assert result["status"] == "AMBIGUOUS" and result["import_attempts"] == 1
        assert import_calls == [1]
        observed = admin.get(KEYS["state"]).encode()
        reconciliation = reconcile_observation(manifest, archive, observed)
        assert reconciliation["status"] == "COMMITTED_PROVENANCE_OBSERVED"
        assert admin.get(KEYS["kill"]).encode() == raws["kill"]
        assert admin.get(KEYS["heartbeat"]).encode() == raws["heartbeat"]
        r.update(
            result=result,
            reconciliation=reconciliation,
            successful_import_dispatches=1,
            response_loss="SYNTHETIC_EXCEPTION_AFTER_ACTUAL_REDIS_SUCCESS_REPLY",
            real_network_disconnect="NOT_EXECUTED",
            no_resend=True,
        )
