"""One-shot import orchestration. This module never starts an orchestrator loop."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from services.orchestrator.legacy_import_contract import (
    CHANNEL,
    SOURCE,
    ImportHoldError,
    OperationDeadlineError,
    build_import_state,
    digest,
    instant,
    load_prepared,
    strict_json,
    validate_legacy,
    validate_package,
    validate_provenance,
)
from services.orchestrator.ownership import LegacyImportConflictError, OwnershipLostError, RedisFencedOwnership


def reconcile_observation(manifest: bytes, archive: bytes, observed_state: bytes) -> dict[str, Any]:
    """Classify supplied bytes offline, including after an operation window ends.

    Historical package validation is anchored just before its expiry solely for
    reconciliation. This function cannot acquire a lease or perform an import.
    """
    end = instant(strict_json(manifest)["package"]["valid_until"])
    package, raws = load_prepared(manifest, archive, now=end - timedelta(microseconds=1))
    result: dict[str, Any] = {
        "operation_id": package["operation_id"],
        "status": "UNKNOWN",
        "observed_state_sha256": digest(observed_state),
        "write_authority": False,
    }
    if observed_state == raws["state"]:
        result["status"] = "LEGACY_BYTES_OBSERVED_NO_RETRY_AUTHORITY"
        return result
    try:
        state = strict_json(observed_state)
        if state["schema"] != "wolf15.orchestrator.state/v2" or state["commit_marker"] != "COMMITTED":
            return result
        provenance = validate_provenance(
            state["legacy_import"], owner=state["owner_id"], generation=state["fence_generation"]
        )
        if type(state["state_revision"]) is not int or state["state_revision"] < 1:
            return result
        expected = {
            "operation_id": package["operation_id"],
            "old_state_sha256": digest(raws["state"]),
            "archive_sha256": digest(archive),
            "archive_reference": package["archive_reference"],
            "legacy_source_commit": package["legacy_source_commit"],
            "importer_source_commit": package["importer_source_commit"],
            "importer_image_digest": package["importer_image_digest"],
            "source_deployment_id": package["source_deployment_id"],
            "legacy_lineage": {
                key: validate_legacy(raws["state"])[key]
                for key in ("source", "channel", "event", "timestamp", "updated_at")
            },
        }
        if (
            state["source"] == SOURCE
            and state["channel"] == CHANNEL
            and all(provenance[key] == value for key, value in expected.items())
        ):
            result["status"] = "COMMITTED_PROVENANCE_OBSERVED"
            result["imported_fence_generation"] = provenance["imported_fence_generation"]
            result["current_fence_generation"] = state["fence_generation"]
    except (ImportHoldError, KeyError, TypeError):
        pass
    return result


def apply_once(client: Any, manifest: bytes, archive: bytes, *, now: datetime | None = None) -> dict[str, Any]:
    """Use one already bound client after protected archive/package verification.

    No retries or post-error read are attempted. Transport ambiguity is returned
    for separate authorized reconciliation. Package assertions are external
    evidence; this function does not invent writer termination or queue counts.
    """
    current_time = now or datetime.now(UTC)
    package, raws = load_prepared(manifest, archive, now=current_time)
    keys = package["keys"]
    ownership = RedisFencedOwnership(
        client,
        owner_id="legacy-import-" + package["operation_id"],
        lease_key=keys["lease"],
        generation_key=keys["generation"],
        ttl_seconds=package["lease_ttl_seconds"],
    )
    result: dict[str, Any] = {
        "operation_id": package["operation_id"],
        "status": "HOLD",
        "lease_release": "NOT_ACQUIRED",
        "import_attempts": 0,
        "archive_sha256": digest(archive),
        "old_state_sha256": digest(raws["state"]),
    }
    stage = "ACQUIRE"
    deadline_expired = False
    try:
        if not ownership.acquire():
            result["reason"] = "OWNER_BUSY"
        else:
            stage = "PREPARE_CAS"
            identity = ownership.identity
            assert identity is not None
            result.update({"owner_id": identity.owner_id, "fence_generation": identity.generation})
            observed = client.mget([keys[name] for name in ("state", "kill", "heartbeat")])
            if observed != [raws[name] for name in ("state", "kill", "heartbeat")]:
                result["reason"] = "FRESH_BYTES_MISMATCH"
            else:
                current_time = now or datetime.now(UTC)
                validate_package(package, now=current_time)
                payload = build_import_state(
                    package,
                    raws,
                    archive_sha256=digest(archive),
                    owner=identity.owner_id,
                    generation=identity.generation,
                    now=current_time,
                )
                result["new_state_sha256"] = digest(payload)
                stage = "CAS_DISPATCHED"
                result["import_attempts"] = 1
                ownership.fenced_legacy_import(
                    state_key=keys["state"],
                    kill_key=keys["kill"],
                    heartbeat_key=keys["heartbeat"],
                    old_state=raws["state"],
                    old_kill=raws["kill"],
                    old_heartbeat=raws["heartbeat"],
                    new_state=payload,
                    valid_until_epoch_ms=int(instant(package["valid_until"]).timestamp() * 1000),
                )
                result["status"] = "COMMITTED"
    except OperationDeadlineError:
        deadline_expired = True
        result["status"] = "AMBIGUOUS" if stage in {"ACQUIRE", "CAS_DISPATCHED"} else "HOLD"
        result["reason"] = "DEADLINE_NO_FURTHER_REDIS_CALLS"
    except (LegacyImportConflictError, OwnershipLostError):
        result["reason"] = "FENCE_OR_CAS_REJECTED"
    except ImportHoldError:
        result["reason"] = "VALIDATION_REJECTED"
    except Exception:
        result["status"] = "AMBIGUOUS" if stage in {"ACQUIRE", "CAS_DISPATCHED"} else "HOLD"
        result["reason"] = "TRANSPORT_OR_BACKEND_FAILURE_NO_RETRY"
        if stage == "ACQUIRE":
            result["lease_release"] = "UNKNOWN_ACQUIRE_OUTCOME"
    finally:
        if deadline_expired:
            result["lease_release"] = "NOT_ATTEMPTED_DEADLINE_LEASE_TTL"
        elif ownership.held:
            try:
                result["lease_release"] = "RELEASED" if ownership.release() else "NOT_HELD_AT_RELEASE"
            except OperationDeadlineError:
                result["lease_release"] = "UNKNOWN_DEADLINE_LEASE_TTL"
                result["reason"] = "DEADLINE_NO_FURTHER_REDIS_CALLS"
            except Exception:
                result["lease_release"] = "UNKNOWN"
        elif stage != "ACQUIRE":
            result["lease_release"] = "NO_LONGER_HELD"
    return result
