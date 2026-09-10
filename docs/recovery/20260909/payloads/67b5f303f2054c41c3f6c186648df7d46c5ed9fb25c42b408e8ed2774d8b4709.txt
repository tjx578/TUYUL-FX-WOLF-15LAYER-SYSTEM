"""Pure, strict contracts for an explicitly approved one-shot legacy import.

Package evidence is supplied by an operator. Validating its shape or hash is
not an observation that its runtime assertions are true.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

SOURCE = "wolf15-orchestrator"
CHANNEL = "wolf15:orchestrator:commands"
PROVENANCE_SCHEMA = "wolf15.orchestrator.legacy-import/v1"
ALGORITHM = "exact-cas-single-set/v1"
PACKAGE_SCHEMA = "wolf15.orchestrator.legacy-import-package/v1"
MAX_BYTES = 262144
REQUIRED_EVIDENCE = frozenset(
    {
        "old_writers_stopped",
        "revival_controlled",
        "execution_off",
        "kill_containment",
        "zero_queues_and_authorities",
        "compatible_recovery",
        "archive_policy",
        "mutation_authorization",
        "release_and_image_binding",
    }
)
KEYS = {
    "state": "wolf15:orchestrator:state",
    "lease": "wolf15:orchestrator:owner",
    "generation": "wolf15:orchestrator:fence_generation",
    "heartbeat": "wolf15:heartbeat:orchestrator",
    "kill": "wolf15:system:kill_switch",
}
PROCESS_IDS = ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_DEPLOYMENT_ID")


class ImportHoldError(ValueError):
    """Fixed, non-secret error code suitable for an operator receipt."""


class OperationDeadlineError(BaseException):
    """Deadline signal that ordinary application/backend handlers cannot swallow."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ImportHoldError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def strict_json(raw: bytes | str) -> Any:
    if len(raw.encode("utf-8") if isinstance(raw, str) else raw) > MAX_BYTES:
        raise ImportHoldError("PAYLOAD_TOO_LARGE")
    try:

        def reject_constant(_value: str) -> Any:
            raise ImportHoldError("NON_FINITE_JSON_NUMBER")

        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise ImportHoldError("INVALID_JSON") from exc


def _shape(value: Any, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ImportHoldError("UNEXPECTED_FIELDS")
    return value


def _text(value: Any, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise ImportHoldError("INVALID_TEXT")
    return value


def _hash(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ImportHoldError("INVALID_SHA256")
    return value


def _integer(value: Any, minimum: int = 1, maximum: int = 2**53 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ImportHoldError("INVALID_INTEGER")
    return value


def _uuid(value: Any) -> str:
    if not isinstance(value, str):
        raise ImportHoldError("INVALID_UUID")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise ImportHoldError("INVALID_UUID") from exc
    return value


def instant(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value, 64).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ImportHoldError("INVALID_TIME") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ImportHoldError("TIMEZONE_REQUIRED")
    return result


def validate_package(value: Any, *, now: datetime) -> dict[str, Any]:
    p = _shape(
        value,
        {
            "schema",
            "operation_id",
            "valid_until",
            "process_binding",
            "endpoint",
            "keys",
            "legacy_source_commit",
            "importer_source_commit",
            "source_deployment_id",
            "importer_image_digest",
            "archive_reference",
            "lease_ttl_seconds",
            "total_timeout_seconds",
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "evidence",
        },
    )
    if p["schema"] != PACKAGE_SCHEMA or p["keys"] != KEYS:
        raise ImportHoldError("PACKAGE_SCHEMA_OR_NAMESPACE_MISMATCH")
    _uuid(p["operation_id"])
    _uuid(p["source_deployment_id"])
    for field in ("legacy_source_commit", "importer_source_commit"):
        if re.fullmatch(r"[0-9a-f]{40}", _text(p[field])) is None:
            raise ImportHoldError("INVALID_SOURCE_COMMIT")
    if not _text(p["importer_image_digest"]).startswith("sha256:"):
        raise ImportHoldError("INVALID_IMAGE_DIGEST")
    _hash(p["importer_image_digest"][7:])
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", _text(p["archive_reference"])) is None:
        raise ImportHoldError("INVALID_ARCHIVE_REFERENCE")
    if now.tzinfo is None or not now < instant(p["valid_until"]):
        raise ImportHoldError("PACKAGE_EXPIRED")
    binding = _shape(p["process_binding"], set(PROCESS_IDS))
    for value in binding.values():
        _uuid(value)
    endpoint = _shape(p["endpoint"], {"scheme", "host", "port", "database"})
    if endpoint["scheme"] not in {"redis", "rediss"}:
        raise ImportHoldError("INVALID_REDIS_SCHEME")
    if re.fullmatch(r"[A-Za-z0-9.-]+", _text(endpoint["host"], 253)) is None:
        raise ImportHoldError("INVALID_REDIS_HOST")
    _integer(endpoint["port"], 1, 65535)
    _integer(endpoint["database"], 0, 15)
    total = _integer(p["total_timeout_seconds"], 1, 600)
    _integer(p["lease_ttl_seconds"], 3, 600)
    if p["lease_ttl_seconds"] <= total:
        raise ImportHoldError("LEASE_MUST_OUTLAST_BOUNDED_OPERATION")
    for field in ("connect_timeout_seconds", "read_timeout_seconds"):
        _integer(p[field], 1, total)
    evidence = _shape(p["evidence"], set(REQUIRED_EVIDENCE))
    for item in evidence.values():
        _shape(item, {"locator", "sha256", "result", "observed_at"})
        _text(item["locator"])
        _hash(item["sha256"])
        if item["result"] != "PASS" or instant(item["observed_at"]) > now:
            raise ImportHoldError("PACKAGE_EVIDENCE_NOT_ACCEPTED")
    return strict_json(encoded(p))


def validate_legacy(raw: bytes) -> dict[str, Any]:
    p = _shape(
        strict_json(raw), {"source", "channel", "mode", "reason", "compliance_code", "updated_at", "timestamp", "event"}
    )
    if p["source"] != SOURCE or p["channel"] != CHANNEL or p["mode"] != "KILL_SWITCH":
        raise ImportHoldError("LEGACY_AUTHORITY_OR_CONTAINMENT_MISMATCH")
    for field in ("reason", "compliance_code", "event"):
        _text(p[field])
    instant(p["updated_at"])
    _integer(p["timestamp"])
    return p


def validate_snapshot(snapshot: Any) -> dict[str, bytes]:
    s = _shape(snapshot, {"state", "kill", "heartbeat"})
    raws: dict[str, bytes] = {}
    for name, item in s.items():
        _shape(item, {"type", "pttl", "base64"})
        if item["type"] != "string" or type(item["pttl"]) is not int or item["pttl"] != -1:
            raise ImportHoldError("SNAPSHOT_TYPE_OR_EXPIRY_MISMATCH")
        try:
            raw = base64.b64decode(_text(item["base64"], MAX_BYTES), validate=True)
        except ValueError as exc:
            raise ImportHoldError("INVALID_BASE64") from exc
        strict_json(raw)
        raws[name] = raw
    validate_legacy(raws["state"])
    kill = strict_json(raws["kill"])
    heartbeat = strict_json(raws["heartbeat"])
    if not isinstance(kill, dict) or kill.get("active") is not True or kill.get("source") != SOURCE:
        raise ImportHoldError("KILL_SWITCH_NOT_ENGAGED")
    if not isinstance(heartbeat, dict) or heartbeat.get("producer") != SOURCE:
        raise ImportHoldError("HEARTBEAT_AUTHORITY_MISMATCH")
    return raws


def validate_provenance(value: Any, *, owner: str, generation: int) -> dict[str, Any]:
    p = _shape(
        value,
        {
            "schema",
            "algorithm",
            "operation_id",
            "old_state_sha256",
            "archive_sha256",
            "archive_reference",
            "legacy_source_commit",
            "importer_source_commit",
            "importer_image_digest",
            "source_deployment_id",
            "legacy_lineage",
            "imported_owner_id",
            "imported_fence_generation",
            "imported_at",
        },
    )
    if p["schema"] != PROVENANCE_SCHEMA or p["algorithm"] != ALGORITHM:
        raise ImportHoldError("PROVENANCE_SCHEMA_MISMATCH")
    _uuid(p["operation_id"])
    _uuid(p["source_deployment_id"])
    _hash(p["old_state_sha256"])
    _hash(p["archive_sha256"])
    for field in ("legacy_source_commit", "importer_source_commit"):
        if re.fullmatch(r"[0-9a-f]{40}", _text(p[field])) is None:
            raise ImportHoldError("INVALID_SOURCE_COMMIT")
    if not _text(p["importer_image_digest"]).startswith("sha256:"):
        raise ImportHoldError("INVALID_IMAGE_DIGEST")
    _hash(p["importer_image_digest"][7:])
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", _text(p["archive_reference"])) is None:
        raise ImportHoldError("INVALID_ARCHIVE_REFERENCE")
    imported_owner = _text(p["imported_owner_id"], 128)
    imported_generation = _integer(p["imported_fence_generation"])
    _text(owner, 128)
    _integer(generation)
    if imported_generation > generation or (imported_generation == generation and imported_owner != owner):
        raise ImportHoldError("PROVENANCE_FENCE_MISMATCH")
    if imported_owner != "legacy-import-" + p["operation_id"]:
        raise ImportHoldError("PROVENANCE_OWNER_MISMATCH")
    instant(p["imported_at"])
    lineage = _shape(p["legacy_lineage"], {"source", "channel", "event", "timestamp", "updated_at"})
    if lineage["source"] != SOURCE or lineage["channel"] != CHANNEL:
        raise ImportHoldError("PROVENANCE_LINEAGE_MISMATCH")
    _text(lineage["event"])
    _integer(lineage["timestamp"])
    instant(lineage["updated_at"])
    return strict_json(encoded(p))


def prepare_documents(package: Any, snapshot: Any, *, now: datetime) -> tuple[bytes, bytes]:
    p = validate_package(package, now=now)
    raws = validate_snapshot(snapshot)
    archive = encoded(
        {
            "schema": "wolf15.orchestrator.legacy-archive/v1",
            "operation_id": p["operation_id"],
            "package_sha256": digest(encoded(p)),
            "snapshot": snapshot,
        }
    )
    manifest = encoded(
        {
            "schema": "wolf15.orchestrator.legacy-import-manifest/v1",
            "package": p,
            "archive_sha256": digest(archive),
            "raw_sha256": {name: digest(raw) for name, raw in raws.items()},
        }
    )
    return archive, manifest


def load_prepared(manifest: bytes, archive: bytes, *, now: datetime) -> tuple[dict[str, Any], dict[str, bytes]]:
    m = _shape(strict_json(manifest), {"schema", "package", "archive_sha256", "raw_sha256"})
    if m["schema"] != "wolf15.orchestrator.legacy-import-manifest/v1" or digest(archive) != m["archive_sha256"]:
        raise ImportHoldError("ARCHIVE_BINDING_MISMATCH")
    a = _shape(strict_json(archive), {"schema", "operation_id", "package_sha256", "snapshot"})
    if a["schema"] != "wolf15.orchestrator.legacy-archive/v1":
        raise ImportHoldError("ARCHIVE_SCHEMA_MISMATCH")
    expected_archive, expected_manifest = prepare_documents(m["package"], a["snapshot"], now=now)
    if archive != expected_archive or manifest != expected_manifest:
        raise ImportHoldError("PREPARED_DOCUMENT_BINDING_MISMATCH")
    return m["package"], validate_snapshot(a["snapshot"])


def build_import_state(
    package: dict[str, Any], raws: dict[str, bytes], *, archive_sha256: str, owner: str, generation: int, now: datetime
) -> bytes:
    legacy = validate_legacy(raws["state"])
    provenance = validate_provenance(
        {
            "schema": PROVENANCE_SCHEMA,
            "algorithm": ALGORITHM,
            "operation_id": package["operation_id"],
            "old_state_sha256": digest(raws["state"]),
            "archive_sha256": archive_sha256,
            "archive_reference": package["archive_reference"],
            "legacy_source_commit": package["legacy_source_commit"],
            "importer_source_commit": package["importer_source_commit"],
            "importer_image_digest": package["importer_image_digest"],
            "source_deployment_id": package["source_deployment_id"],
            "legacy_lineage": {key: legacy[key] for key in ("source", "channel", "event", "timestamp", "updated_at")},
            "imported_owner_id": owner,
            "imported_fence_generation": generation,
            "imported_at": now.astimezone(UTC).isoformat(),
        },
        owner=owner,
        generation=generation,
    )
    return encoded(
        {
            **legacy,
            "schema": "wolf15.orchestrator.state/v2",
            "commit_marker": "COMMITTED",
            "state_revision": 1,
            "owner_id": owner,
            "fence_generation": generation,
            "event": "IMPORT_COMMITTED",
            "timestamp": int(now.timestamp()),
            "legacy_import": provenance,
        }
    )


def validate_import_state(raw: bytes, *, old_state: bytes, owner: str, generation: int) -> None:
    old = validate_legacy(old_state)
    new = _shape(
        strict_json(raw),
        set(old) | {"schema", "commit_marker", "state_revision", "owner_id", "fence_generation", "legacy_import"},
    )
    if (
        new["schema"] != "wolf15.orchestrator.state/v2"
        or new["commit_marker"] != "COMMITTED"
        or type(new["state_revision"]) is not int
        or new["state_revision"] != 1
        or new["owner_id"] != owner
        or new["fence_generation"] != generation
        or new["event"] != "IMPORT_COMMITTED"
    ):
        raise ImportHoldError("IMPORT_ENVELOPE_MISMATCH")
    _integer(new["timestamp"])
    for name in ("source", "channel", "mode", "reason", "compliance_code", "updated_at"):
        if new[name] != old[name]:
            raise ImportHoldError("IMPORT_SEMANTIC_CHANGE_REJECTED")
    provenance = validate_provenance(new["legacy_import"], owner=owner, generation=generation)
    expected_lineage = {key: old[key] for key in ("source", "channel", "event", "timestamp", "updated_at")}
    if (
        provenance["old_state_sha256"] != digest(old_state)
        or provenance["legacy_lineage"] != expected_lineage
        or provenance["imported_fence_generation"] != generation
        or provenance["imported_owner_id"] != owner
    ):
        raise ImportHoldError("IMPORT_PROVENANCE_MISMATCH")
