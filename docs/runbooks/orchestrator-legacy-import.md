# Explicit legacy state import — local candidate

This utility prepares a future, separately reviewed P2 transition. Its local
source/offline tests do not authorize production reads, mutation or cutover.
There is no startup migration fallback, automatic retry, compliance loop,
issuance, counter reset, ledger deletion or kill-switch change.

## Storage and authority model

The observed legacy namespace is the only supported namespace in version1:
`wolf15:orchestrator:state`, `wolf15:orchestrator:owner`,
`wolf15:orchestrator:fence_generation`, `wolf15:system:kill_switch` and
`wolf15:heartbeat:orchestrator`. A different namespace requires source review.
Legacy state must have exactly the eight owner-free fields in the contract and
mode KILL_SWITCH. The state, kill switch and heartbeat must be persistent Redis
strings (PTTL=-1). Unknown legacy fields, malformed/duplicate/nonfinite JSON,
different authority, inactive kill switch or expiring keys fail closed.

Preparation creates two distinct files: a protected archive containing the
exact original bytes as base64, and a canonical manifest binding their hashes
to an operation ID and operator package. JSON reserialization does not alter
the original bytes inside the archive. The archive must be persisted and read
back successfully before apply. A failed manifest write leaves any completed
archive intact; the utility never deletes it or overwrites existing files.

Apply acquires a real lease through `RedisFencedOwnership.acquire`. The normal
counter increments in Redis; there is no invented predecessor generation. A
single final SET stores the new v2 state **and** import provenance as one value.
Before that SET, the Lua script verifies distinct keys, types, exact old
state/kill/heartbeat bytes, persistent TTLs, current lease value with positive
PTTL, the Redis server clock against package expiry, and the import envelope.
All validation precedes the sole migration write. A script error before SET
cannot leave a partially written archive/provenance key because there is no
second migration key. Lease acquisition/release remain separate legitimate
lease operations.

The import leaves kill-switch and heartbeat bytes unchanged and publishes no
channel message. The heartbeat remains the old observation; import does not
claim a healthy running orchestrator. The new v2 history begins at revision1
under the actual importer owner/generation. Original mode, reason,
compliance_code and updated_at are retained. New event IMPORT_COMMITTED and
actual import time are separate from the archived original event/timestamp.

`legacy_import` provenance is validated and retained by normal v2 hydration and
every subsequent `publish_state` call, including BOOT, MODE_CHANGED, HEARTBEAT
and SHUTDOWN. It includes the operation ID, raw state hash, archive hash and
non-secret reference, original owner-free lineage, actual imported owner/fence,
and the separate producer/importer identities below. Malformed optional
provenance fails before publication. The existing rejected-hydration guard
still prevents default-state SHUTDOWN from overwriting rejected bytes.

The runtime change also makes **all** persisted v2 hydration use strict JSON:
duplicate keys and nonfinite numbers are rejected, and the UTF-8 payload limit
is256KiB. This is broader than optional provenance handling. Offline tests
cover ordinary v2 below/at/above that boundary, duplicate/nonfinite payloads,
including exponent overflow such as nested `1e999`, and existing normal
state/recovery behavior. This local change is not yet
evidence that every historic production v2 payload fits the new bound.

## Required package and evidence

Use `wolf15.orchestrator.legacy-import-package/v1`. The contract requires these
fields, with no production defaults:

| Field | Meaning |
|---|---|
| operation_id, valid_until | Unique UUID and explicit UTC/offset-bearing expiry; a retry never silently reuses authority. |
| process_binding | Exact RAILWAY_PROJECT_ID, RAILWAY_ENVIRONMENT_ID, RAILWAY_SERVICE_ID, RAILWAY_DEPLOYMENT_ID of the importer process. |
| endpoint | Explicit Redis scheme, host, port and logical database; credential URL must match exactly and cannot override settings with a query string. |
| keys | Exact supported names listed above. |
| legacy_source_commit, source_deployment_id | Prior legacy producer source commit and deployment; these are provenance, not the importer release. |
| importer_source_commit, importer_image_digest | Reviewed utility source commit and the exact image intended to execute it; image metadata must be independently bound by package evidence. |
| archive_reference | Non-secret stable reference; no credential URL or embedded password. The actual archive path is an explicit CLI argument. |
| operation_marker_path | Canonical absolute POSIX path in the approved persistent operation ledger, ending with operation_id plus `.attempt.json`. This immutable package field is independent of archive, manifest and receipt output locations. |
| lease_ttl_seconds | Approved existing/planned lease setting; it must outlast total_timeout_seconds and pass the ownership implementation's minimum. |
| total_timeout_seconds, connect_timeout_seconds, read_timeout_seconds | Explicit bounded operation and socket limits; fixture numbers are not operator policy. |
| evidence | Required named gate records below, each with a local artifact locator, SHA256, result PASS and observation time. |

Required gate names are old_writers_stopped, revival_controlled, execution_off,
kill_containment, zero_queues_and_authorities, compatible_recovery,
archive_policy, mutation_authorization, release_and_image_binding and
persistent_operation_ledger.
The CLI verifies referenced file hashes. Those records are supplied operator
evidence; a valid hash/schema does **not** independently observe their runtime
claims. Do not create PASS records from missing measurements.

Prove termination of every unfenced legacy writer, including embedded API
instances, and prevent revival before applying. Missing owner/generation keys
do not prove termination. Preserve the zero-queue/authority conditions in the
cutover runbook and keep execution OFF. A compatible recovery image must
already understand committed v2 and the same fence namespace. The old unfenced
legacy image is not an eligible recovery artifact after import. A provider's
canRollback flag alone does not close that gate.

The snapshot input has state, kill and heartbeat entries, each containing
`type`, `pttl` and `base64`. Obtaining those raw bytes is a separate authorized
observation; this utility's prepare command never connects to Redis.
The earlier metadata-only production snapshot is not a raw archive or a fresh
CAS precondition.

## Explicit commands

All paths below are placeholders for a reviewed operator package. No command
in this runbook supplies an endpoint, password, account, risk or operation
window. Never put credential values on argv or in a file/chat receipt.

```text
python -m services.orchestrator.legacy_import_cli prepare --package PACKAGE --snapshot SNAPSHOT
```

Preparation defaults to dry validation and writes nothing. To create the
protected archive and manifest, explicitly add `--write-archive --archive
ARCHIVE --manifest MANIFEST`. Their existing parent directories must be owned
by the current Linux UID and mode0700; files are created exclusively with
mode0600, no symlink following, one hard link, fsync and read-back verification.
The tool does not create/chmod/chown the parent. Parent provisioning and
mounted-volume permissions belong to the approved package.

Windows supports dry preparation only. Protected archive creation, protected
archive reads and apply intentionally return HOLD on Windows. The local test
suite uses an explicitly labeled fake protected-store boundary for CLI apply;
it does not establish POSIX permission or Railway volume evidence.

```text
python -m services.orchestrator.legacy_import_cli apply --archive ARCHIVE --manifest MANIFEST
```

This validates protected inputs without a connection. Execution additionally
requires all of `--enable-apply --credential-env EXISTING_REFERENCE_NAME
--receipt NEW_RECEIPT`. The named environment value is used in memory only.
The four actual Railway process IDs must match the package. There is no
fallback credential, admin identity or default production target.

Before any connection, an exclusive protected operation-ID attempt marker is
persisted at the package-bound path. Relocating archive/manifest files or
choosing another receipt directory cannot change that path. Changing the path
inside a manifest breaks its original protected archive/package binding;
creating a different package would require its own reviewed authority.
Normalized archive, manifest, marker and receipt paths must not alias. In
particular, a receipt equal to the marker holds before consuming an attempt or
connecting. Existing markers/receipts fail closed. The parent must already
exist with owner-only permissions. Path validation is not proof of a mounted
or persistent volume: the persistent_operation_ledger evidence must bind the
actual persistent location and its lifetime independently of a job container.

An empty or root URL path is accepted as Redis database0 only when the explicit
approved package binding is database0. The credential value is returned
unchanged; the utility never rewrites a credential URL. Nonzero database
bindings still require the matching explicit URL path. Endpoint, query,
fragment and credential checks remain enforced. The driver uses one initial
connection with retry count0. A connection wrapper forbids implicit reconnect
or further network calls after a failed call. Backend exceptions are not
serialized. The configured driver interface was inspected locally against
redis-py7.3.0; actual deployment driver behavior remains a real-server gate.

SIGALRM raises a dedicated BaseException deadline signal. During acquire or
CAS, it records ambiguity and prevents any subsequent Redis call, including a
network release. Local client close still runs; a possibly held lease expires
under its real TTL. A deadline during release records its outcome as unknown.
Separate injected deadline tests prove the application control flow; Windows
offline tests do not establish actual Linux signal delivery, DNS interruption
or process-stop timing. Bind a real external watchdog/stop command and its
approved grace period in the deployment package before production execution.

## Ambiguity and recovery

A lost CAS response produces AMBIGUOUS. An acquire response loss may also
leave a real lease, so the receipt does not claim it was never acquired.
Do not retry or reset the generation. Use the operation marker and a separately
authorized state observation for reconciliation. The offline command is:

```text
python -m services.orchestrator.legacy_import_cli reconcile --archive ARCHIVE --manifest MANIFEST --state-observation OBSERVED_STATE
```

This command reads supplied protected files only. It can recognize carried
provenance after a successor BOOT and can run after the original apply window
expires. Reconciliation grants no write authority. An unchanged legacy value
is an observation, not permission to reapply. Different or malformed
provenance remains UNKNOWN.

If an acknowledged commit cannot be saved to the requested receipt, the CLI
returns failure with RESULT_PERSISTENCE_FAILED and the observed backend status.
The consumed marker and archive remain; no automatic retry follows. If the
receipt says COMMITTED with an unknown lease-release outcome, that is not
permission to bypass takeover/TTL verification. A successor must acquire its
own strictly newer lease generation and keep all issuance/kill gates valid.

Before import, recovery leaves legacy bytes intact. After import, recovery
preserves v2 history and uses a compatible fenced artifact/configuration.
Never restore legacy bytes over newer state, revive an embedded writer,
delete/reset lease or generation keys, roll back the database or erase ledgers.

## Verification boundary

The focused offline suite exercises pure validation, a deterministic Redis
contract model, actual Python StateManager full-run behavior, fake protected
CLI boundaries, signal injection, no-reconnect behavior and source assertions.
It does not execute Lua. Real Redis CAS/error/type/race behavior, actual driver
handshake and reconnect suppression, Linux archive fsync/permissions/signals,
container startup and all production gates remain NOT_EXECUTED for this
candidate until independently reviewed and explicitly scheduled.
