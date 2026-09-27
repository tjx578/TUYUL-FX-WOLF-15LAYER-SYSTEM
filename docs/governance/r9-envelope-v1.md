# R9EnvelopeV1 - exact snapshot S evidence envelope

- status: FROZEN
- envelope_status: FROZEN (owner freeze 2026-09-28 of the exact predecessor bytes recorded in section 8; any
  byte change to sections 1-7 is a new version and a new freeze, never an edit)
- runtime_activation: false (source/test only; no runtime path imports `contracts/r9_envelope_v1.py`)
- contract: `contracts/r9_envelope_v1.py`
- tests: `tests/test_r9_envelope_v1.py`
- lineage: operator evidence run R9 of the D0 exact-S chain (authenticated D0 reconciliation gate, PR #419)

## 1. Purpose

R9 is the operator evidence run for exact snapshot S:

    identity S -> collect -> import -> ACTIVE readback -> capability -> direct receipt

`R9EnvelopeV1` is a strict, fail-closed envelope that states, for ONE source R9 evidence artifact, which
snapshot identity each stage bound. The verifier derives one boolean, `exact_s_accepted`. It never grants trade
authority, never selects a snapshot, never falls back to "latest", and has no default for any field.

## 2. Field list (normative; must equal `r9_envelope_field_paths_v1()`)

Wire keys; nested components are dotted. `import` is the wire key (Python attribute `import_`).
`exact_s_accepted` is DERIVED and exists only on the verifier verdict: it is never an input field.

<!-- r9-envelope-fields:begin -->
```text
schema_id
schema_version
source_artifact
artifact_sha256
snapshot_s.snapshot_id
snapshot_s.snapshot_sha256
collect.status
collect.attested_snapshot_identity.snapshot_id
collect.attested_snapshot_identity.snapshot_sha256
collect.evidence_id
collect.report_sha256
import.status
import.imported_snapshot_identity.snapshot_id
import.imported_snapshot_identity.snapshot_sha256
import.evidence_id
import.payload_sha256
active_readback.status
active_readback.readback_snapshot_identity.snapshot_id
active_readback.readback_snapshot_identity.snapshot_sha256
active_readback.evidence_id
active_readback.payload_sha256
capability.status
capability.snapshot_id
capability.canonical_symbol
capability.broker_symbol
capability.volume_min
capability.volume_step
direct_receipt.status
direct_receipt.snapshot_id
direct_receipt.reconciliation_id
direct_receipt.receipt_sha256
direct_receipt.broker_ledger_reconciled
created_at
exact_s_accepted
```
<!-- r9-envelope-fields:end -->

## 3. Types and the source of every reused name

All models: pydantic, `extra="forbid"`, `frozen=True`. Every field is required (no defaults); a field typed
`| None` must still be supplied explicitly.

| Field | Type | Reused from (file:line) |
|---|---|---|
| `schema_id` | `Literal["wolf15.r9-envelope"]` | NEW_IN_R9_ENVELOPE (the envelope itself is new) |
| `schema_version` | `Literal["v1"]` | NEW_IN_R9_ENVELOPE (the envelope itself is new) |
| `source_artifact` | `str`, 1..64; acceptance requires `"R9"` | NEW_IN_R9_ENVELOPE (owner-locked value `R9`; run id `C2_RECONCILIATION_R9` in the operator coordinator, outside main) |
| `artifact_sha256` | 64 lowercase hex | NEW_IN_R9_ENVELOPE (owner-locked); hex format reused from `execution/broker_reconciliation_evidence.py:73` |
| `*.snapshot_id` | `str`, 3..200 | `contracts/mt5_execution_protocol.py:454` (`AccountSnapshotV1.snapshot_id`); `execution/broker_reconciliation_evidence.py:72` |
| `*.snapshot_sha256` | 64 lowercase hex | `execution/broker_reconciliation_evidence.py:73` (`ReconciliationAttestation.snapshot_sha256`), computed by `snapshot_digest` at `:42` |
| `collect.status` | `Literal["MATCHED_FLAT_DEMO"]` | `execution/broker_reconciliation_evidence.py:75` |
| `collect.attested_snapshot_identity` | snapshot identity | the attestation's `snapshot_id`/`snapshot_sha256` (`:72-73`), bound to backend identity S by `attest_collected_reconciliation` (`:127`, exact-S guard `:146-159`) |
| `collect.evidence_id` | UUID | `execution/broker_reconciliation_evidence.py:67` |
| `collect.report_sha256` | 64 lowercase hex | `execution/broker_reconciliation_evidence.py:74` |
| `import.status` | `Literal["STORED"]` | QUALIFIED_C2_WRAPPER_STATUS, normalized as the R9 import status; NOT a main-repository canonical status (`mirror_control/c2b_writer.py:86`, OUTSIDE main). In main, `store_evidence` returns the digest or raises (`execution/broker_reconciliation_repository.py:149-189`). It only states that the wrapper finished the import; persistence is proven by the main-side ACTIVE readback (same `evidence_id`, same `payload_sha256`, same S) |
| `import.imported_snapshot_identity` | snapshot identity | `store_evidence` loads S by `snapshot_id` and re-verifies `snapshot_sha256` via `verify_attestation` (`execution/broker_reconciliation_evidence.py:113-116`) |
| `import.evidence_id` | UUID | row key `evidence_id` inserted at `execution/broker_reconciliation_repository.py:170-173` |
| `import.payload_sha256` | 64 lowercase hex | `execution/broker_reconciliation_repository.py:167-178` (`digest(evidence)` stored as `payload_sha256`) |
| `active_readback.status` | `Literal["ACTIVE", "REVOKED"]` | `storage/migrations/versions/20260910_02_reconciliation_evidence.py:36`; ACTIVE check `execution/broker_reconciliation_repository.py:137` |
| `active_readback.readback_snapshot_identity` | snapshot identity | row `snapshot_id` of `broker_reconciliation_evidence` (`storage/migrations/versions/20260910_02_reconciliation_evidence.py:33`), read by `load_evidence` (`execution/broker_reconciliation_repository.py:128-141`) and by the C2 wrapper post-commit readback keyed by `evidence_id` (`mirror_control/c2b_writer.py:40-63`, OUTSIDE main) |
| `active_readback.evidence_id` | UUID | same row, `evidence_id` |
| `active_readback.payload_sha256` | 64 lowercase hex | same row, `payload_sha256` (`execution/broker_reconciliation_repository.py:141`) |
| `capability.status` | `Literal["MEASURED", "MEASURED_EMPTY", "NOT_MEASURED"]` | `ops/mt5_mcp/reconcile.py:29` (`MEASURED_STATES`) and `:332` (`NOT_MEASURED`) |
| `capability.snapshot_id` | `str`, 3..200 | view `wolf15_audit.executor_snapshot_symbol_capability_v1` keyed by exact `snapshot_id` only (`storage/migrations/versions/20260919_01_d0_canary_predicate_audit_views.py:26-47`); the view proves no `snapshot_sha256`, so none is claimed |
| `capability.canonical_symbol` | `str`, 3..32, or null | `contracts/mt5_execution_protocol.py:399` (`SymbolCapability`); view column `:34` |
| `capability.broker_symbol` | `str`, 1..64, or null | `contracts/mt5_execution_protocol.py:400`; view column `:35` |
| `capability.volume_min` | `float > 0`, or null | `contracts/mt5_execution_protocol.py:406`; view column `:39` |
| `capability.volume_step` | `float > 0`, or null | `contracts/mt5_execution_protocol.py:408`; view column `:41` |
| `direct_receipt.status` | `Literal["ABSENT", "PRESENT"]` | NEW_IN_R9_ENVELOPE (owner-locked); existing code only has "row found / no row" for view `wolf15_audit.direct_reconciliation_receipt_v1` (`storage/migrations/versions/20260919_01_d0_canary_predicate_audit_views.py:49-74`) |
| `direct_receipt.snapshot_id` | `str`, 3..200 | receipt `source_snapshot_id` (`contracts/direct_broker_reconciliation.py:96`), the gate lookup `execution/mt5_command_repository.py:1173`; the receipt's `source_snapshot_sha256` hashes `DirectBrokerSourceSnapshotV1` (`execution/direct_broker_reconciliation_repository.py:77`), not S, so it is never compared |
| `direct_receipt.reconciliation_id` | UUID or null | `contracts/direct_broker_reconciliation.py:90` |
| `direct_receipt.receipt_sha256` | `sha256:` + 64 lowercase hex, or null | `contracts/direct_broker_reconciliation.py:106` |
| `direct_receipt.broker_ledger_reconciled` | bool or null | `contracts/direct_broker_reconciliation.py:103`; audit view column `storage/migrations/versions/20260919_01_d0_canary_predicate_audit_views.py:56` |
| `created_at` | timezone-aware UTC datetime | NEW_IN_R9_ENVELOPE (owner-locked name; existing tables use `created_at`, contracts use `*_at_utc`) |
| `exact_s_accepted` | bool, DERIVED, verifier verdict only | NEW_IN_R9_ENVELOPE (owner-locked); never accepted from input; the envelope exposes only `intrinsic_checks_passed` |

Snapshot identity (`R9SnapshotIdentityV1`) is exactly the pair `(snapshot_id, snapshot_sha256)` that the
backend binding pins (`executor_reconciliation_bindings`, written at
`execution/broker_reconciliation_repository.py:57-80`). No new alias for S is introduced.

## 4. Acceptance (derived; never trusted from input)

`exact_s_accepted` (verifier verdict only) is TRUE only if every rule holds; otherwise FALSE with the ordered
failure reasons of section 5. For collect, import and ACTIVE readback, equality with S is equality of BOTH
`snapshot_id` and `snapshot_sha256`; the capability and direct-receipt views prove `snapshot_id` only (rule 5).

1. The input does not supply `exact_s_accepted` (any supplied value is rejected, even a correct one).
2. The envelope validates against the schema: all fields present, no extra field, every Literal/format holds
   (missing component, unknown status, bad sha256 format -> FALSE).
3. `source_artifact == "R9"`.
4. Artifact bytes are REQUIRED: `verify_r9_envelope_v1(envelope, None)` fails with `ARTIFACT_BYTES_REQUIRED`;
   otherwise `sha256(artifact_bytes) == artifact_sha256`. `artifact_sha256` hashes the SOURCE R9 evidence
   artifact bytes, never the envelope (no circular hashing). No path yields `exact_s_accepted = true` without
   verified bytes.
5. `snapshot_s == collect.attested_snapshot_identity == import.imported_snapshot_identity
   == active_readback.readback_snapshot_identity` (full pair), and
   `capability.snapshot_id == direct_receipt.snapshot_id == snapshot_s.snapshot_id` (id only).
6. Evidence chain: `import.evidence_id == collect.evidence_id`; `active_readback.evidence_id ==
   import.evidence_id`; `active_readback.payload_sha256 == import.payload_sha256`.
7. `active_readback.status == "ACTIVE"`.
8. `capability.status == "MEASURED"` and all four capability evidence fields are non-null.
9. `direct_receipt.snapshot_id == snapshot_s.snapshot_id` for both ABSENT and PRESENT: ABSENT means the
   receipt for exactly S was looked up and no row exists, never that no receipt exists for some snapshot.
10. `direct_receipt.status == "ABSENT"` (expected today): `reconciliation_id`, `receipt_sha256` and
    `broker_ledger_reconciled` are all null.
11. `direct_receipt.status == "PRESENT"`: `reconciliation_id` and `receipt_sha256` are non-null and
    `broker_ledger_reconciled == true`; false or null is `DIRECT_RECEIPT_NOT_RECONCILED`.

There is no fallback to a latest snapshot and no default: a newer snapshot S+1 anywhere in the chain is an
identity mismatch, never a substitute.

## 5. Failure reason vocabulary (normative order; must equal `R9_FAILURE_REASONS_V1`)

A verdict lists its reasons in exactly this order. The first two are terminal (no further reasons are derived
from an input that supplied `exact_s_accepted` or failed the schema).

<!-- r9-envelope-failure-reasons:begin -->
```text
EXACT_S_ACCEPTED_SUPPLIED_BY_INPUT
ENVELOPE_SCHEMA_INVALID
SOURCE_ARTIFACT_NOT_R9
ARTIFACT_BYTES_REQUIRED
ARTIFACT_SHA256_MISMATCH
COLLECT_SNAPSHOT_IDENTITY_MISMATCH
IMPORT_SNAPSHOT_IDENTITY_MISMATCH
IMPORT_EVIDENCE_ID_MISMATCH
ACTIVE_READBACK_STATUS_NOT_ACTIVE
ACTIVE_READBACK_SNAPSHOT_IDENTITY_MISMATCH
ACTIVE_READBACK_EVIDENCE_ID_MISMATCH
ACTIVE_READBACK_PAYLOAD_SHA256_MISMATCH
CAPABILITY_STATUS_NOT_MEASURED
CAPABILITY_EVIDENCE_MISSING
CAPABILITY_SNAPSHOT_ID_MISMATCH
DIRECT_RECEIPT_SNAPSHOT_ID_MISMATCH
DIRECT_RECEIPT_PRESENT_WITHOUT_RECEIPT_IDENTITY
DIRECT_RECEIPT_NOT_RECONCILED
DIRECT_RECEIPT_ABSENT_WITH_RECEIPT_IDENTITY
```
<!-- r9-envelope-failure-reasons:end -->

## 6. Verifier

`verify_r9_envelope_v1(envelope, artifact_bytes: bytes | None) -> R9EnvelopeVerdictV1` accepts a parsed
`R9EnvelopeV1` or a raw mapping, never raises on malformed input, and returns
`{exact_s_accepted, failure_reasons, artifact_bytes_verified}`. The verdict is the ONLY final
`exact_s_accepted` authority, because only the verifier holds the artifact bytes; the verdict model itself
refuses `exact_s_accepted = true` with any failure reason or without verified bytes. The envelope exposes
`intrinsic_checks_passed` / `intrinsic_failure_reasons` (every rule except the bytes), which are never acceptance.

## 7. Owner decisions (2026-09-28)

```text
Q1  NARROW TO ID-ONLY - capability and direct receipt compare snapshot_id only; S's sha256 is never copied
    into them as if it were extra evidence.
Q2  KEEP - evidence chain (evidence_id collect = import = readback; payload_sha256 import = readback) and
    ABSENT naming exact S.
Q3  YES - PRESENT requires broker_ledger_reconciled == true (DIRECT_RECEIPT_NOT_RECONCILED otherwise);
    ABSENT carries null reconciliation_id, receipt_sha256 and broker_ledger_reconciled.
Q4  REQUIRED - artifact bytes are mandatory (ARTIFACT_BYTES_REQUIRED); the verifier verdict is the only final
    exact_s_accepted authority; the envelope exposes intrinsic_checks_passed only.
Q5  ACCEPT STORED - explicitly QUALIFIED_C2_WRAPPER_STATUS / R9-normalized import status, not a main
    canonical status; proven again by the main-side ACTIVE readback.
```

## 8. Freeze record (owner, 2026-09-28)

The owner verified the exact bytes below against the GitHub head and froze them. This successor changes
metadata only: the two header status lines and this section. Sections 1-7 are byte-identical to the frozen
bytes, pinned by `frozen_normative_span_sha256` (from `## 1.` up to the blank line before `## 8.`).

```text
frozen_schema_head             = 08c2de61d2ffe2da41ae4d04da8255319310c424
frozen_schema_blob             = 9a895e34cd1547047e76d2646b3633cdac04cd13
frozen_schema_sha256           = 10732eebab7e8a3a9270be6d378689e6160bd7a8087520ee2d86bf156e7588a2
frozen_schema_bytes            = 13162
frozen_normative_span_sha256   = c9663fa7a752baa8f8723ef0241980d7fc9a55938ff480dc5703564e4e31b96f
frozen_by                      = OWNER
frozen_on                      = 2026-09-28
evidence                       = PR #517 head 08c2de61: CI 40/40, Security Gate PASS; 144 targeted, 199 neighbour,
                                 mutation 46/46; runtime effect 0
envelope_status                = FROZEN
decisions_locked               = Q1, Q2, Q3, Q4, Q5 (section 7)
exact_s_final_authority        = verify_r9_envelope_v1 verdict ONLY
artifact_bytes                 = REQUIRED
latest_snapshot_fallback       = PROHIBITED
runtime_activation             = FALSE
risk_authority                 = FALSE
execution_authority            = FALSE
broker_effect                  = 0
```

A frozen schema is not an R9 PASS: `exact_s_accepted` stays FALSE until a real R9 artifact is produced and
verified by `verify_r9_envelope_v1` with its bytes.
