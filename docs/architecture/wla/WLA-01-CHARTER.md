# WLA-01 Contract-Only Charter

Charter ID: `WLA01-CHARTER-20260824-001`

Stage status: `AWAITING_HUMAN_DECISION`

Authorization ceiling: `CONTRACT_ONLY`

WLA-00 authority: ratification `de760418-7c42-4cfc-b1cf-a8f472aefba4`,
canonical verdict `PASS`, signed owner attestation
[`726f368aaa5f549348674be8eac0a29578412b40`](https://github.com/tuyul-ai-agi/TUYUL-KARTEL-FX-AGI-HYBRID/commit/726f368aaa5f549348674be8eac0a29578412b40).

WOLF15 base: `7ff2a9194b22e185b35dc61574c61628ba404939`

Implementation branch: `codex/wla-01-contract-only`

## 1. Objective

WLA-01 defines and tests the source-owned `AlphaLearningEnvelopeV1` boundary
for two observational exports:

- `wolf15.alpha-fact.exported.v1`; and
- `wolf15.outcome-evidence.exported.v1`.

This stage produces a pure contract, canonical fixtures, and tests. It neither
registers the contract in runtime nor transports, persists, dispatches, or
consumes an event.

## 2. Authorized deliverables

1. One frozen Pydantic v2 envelope contract under `contracts/`.
2. A closed discriminated payload allowlist for the two source event families.
3. Canonical UTF-8 JSON, stable event identity, payload hashing, an exact
   non-self-referential envelope-hash projection, and domain-separated Ed25519
   producer authentication.
4. A no-storage/no-network structural parser that returns only `UNTRUSTED`, plus
   a fail-closed authenticated verifier as the sole path to `ACCEPTED`.
5. Deterministic positive and fail-closed negative fixtures.
6. Pure contract tests, security/authority tests, and a verification receipt.
7. A WLA-01 human decision packet after the evidence is complete.

## 3. Explicit non-goals and prohibitions

WLA-01 MUST NOT add or modify:

- module auto-registration or a runtime import path;
- database schemas, migrations, outboxes, queues, cursors, schedulers, or
  dispatchers;
- Journal ingestion, acknowledgements, or consumer receipts;
- credentials, network clients, service configuration, deployment artifacts, or
  workflows;
- broker, EA, order-router, risk-reservation, verdict, execution, or advisory
  activation;
- Episode, Outcome-label, Replay, Reflection, Dataset, Challenger, or SHADOW
  runtime behavior; or
- any learning repository.

The frozen `feat/observer-telemetry-export-v1` worktree is prior art and remains
unchanged. This branch is a distinct worktree based on its exact approved SHA.

## 4. Contract decisions

| Research decision | WLA-01 resolution |
| --- | --- |
| `WLA01-RD-001` owner/location/base | WOLF15 owns the source contract; isolated branch from `7ff2a919...`; no edits to the frozen worktree |
| `WLA01-RD-002` stable identity | UUIDv5 over `event_name + event_version + source_system + logical_event_key`; deployment is provenance, not identity |
| `WLA01-RD-003` temporal ownership | Source export carries only occurred, observed, and source-published clocks; receipt/ingestion/learning-availability clocks are forbidden here |
| `WLA01-RD-004` canonicalization/hash | Sorted-key compact UTF-8 JSON, no NaN/duplicate keys; payload hash covers typed payload; envelope hash excludes its own field and the producer signature to avoid circularity; Ed25519 signs the complete canonical unsigned envelope including the resulting hashes |
| `WLA01-RD-005` registry/compatibility | Exactly two event names and seven typed payload variants; unknown event, version, type, field, or nested field fails closed |
| `WLA01-RD-006` Outcome Evidence | Full fill, partial fill, reject, cancel, and approved horizon observation are source evidence; no derived outcome label exists in this contract |
| `WLA01-RD-007` limits | 65,536 canonical bytes, 32 direct refs, 16 reasons, 16 missing fields, sealed ancestry above the inline-ref limit |
| `WLA01-RD-008` unavailable identity/clock | Events may be preserved only as `QUARANTINED` with matching typed reason and uncertainty flags; they cannot become `VALID` |

## 5. Closed event and payload registry

| Event | Schema ID | Required authority | Allowed payload discriminators |
| --- | --- | --- | --- |
| `wolf15.alpha-fact.exported.v1` | `urn:wolf15:wla:schema:alpha-fact-exported:v1` | `WOLF15_CANONICAL_ALPHA` | `canonical-alpha-decision.v1`, `canonical-alpha-abstention.v1` |
| `wolf15.outcome-evidence.exported.v1` | `urn:wolf15:wla:schema:outcome-evidence-exported:v1` | `WOLF15_SOURCE_OUTCOME_EVIDENCE` | `fill-evidence.v1`, `partial-fill-evidence.v1`, `reject-evidence.v1`, `cancel-evidence.v1`, `horizon-observation-evidence.v1` |

The payload is not a generic dictionary. Pydantic selects a frozen model by
`payload_type`; every nested model uses `extra=forbid` and strict validation.

## 6. Temporal and leakage boundary

The source temporal profile requires:

```text
occurred_at_utc <= observed_at_utc <= source_published_at_utc
```

It also records precision, clock health, and maximum declared skew. Fields such
as `first_received_at_utc`, `ingested_at_utc`, and
`learning_available_at_utc` belong to a future Journal-owned receipt and are
rejected as extra fields in WLA-01.

Outcome Evidence is an observation, not an Outcome label. Horizon evidence
records source prices and a pinned horizon policy; it carries no win/loss,
profitability, training target, or maturity label. Price touch or order intent
alone cannot become an authoritative fill.

## 7. Authority and safety invariants

Every accepted envelope requires these literal values:

```text
source_interaction_authority = OBSERVATIONAL_ONLY
wla_decision_authority       = NONE
wla_gate_authority           = NONE
can_mutate_source            = false
can_issue_verdict            = false
can_execute                  = false
can_self_promote             = false
```

They are required serialized fields, not defaults or feature flags. A source
payload may truthfully mirror whether a canonical WOLF15 Alpha was valid for
execution at the source, but this never transfers capability to WLA.

## 8. Canonicalization and integrity

Canonicalization version `wolf15.wla.canonical-json.v1` is:

- JSON encoded as UTF-8 without BOM;
- keys sorted lexicographically;
- compact separators `,` and `:`;
- Unicode preserved without ASCII escaping;
- no duplicate keys or non-finite numeric constants; and
- exact canonical bytes required by the reference parser.

`payload_hash` is SHA-256 over the canonical typed payload. `envelope_hash` is
SHA-256 over the canonical unsigned envelope with
`integrity.envelope_hash` and `producer_authentication.signature` omitted. The
payload hash, authentication version, algorithm, signature domain, producer
role, key ID, and canonicalization version remain inside that projection.

The Ed25519 preimage is the ASCII domain
`WOLF15_ALPHA_LEARNING_ENVELOPE_V1`, followed by one NUL byte and the complete
canonical unsigned envelope. Unlike the envelope-hash projection, the signed
unsigned envelope includes `integrity.envelope_hash`; therefore the signature
binds event identity and type, schema/version, source identity, source role, key
ID, payload, payload hash, and envelope hash. This signing domain is distinct
from human governance signatures and WOLF15 execution-command signatures.

Structural parsing validates bytes, types, canonicalization, IDs, hashes,
authority, and safety, but always returns `trust_status=UNTRUSTED`. It does not
prove origin. Only `authenticate_alpha_learning_envelope_v1`, called with an
explicit producer-key allowlist and explicit known-event hash view, may return
`trust_status=ACCEPTED`. It rejects unknown, revoked, wrong-domain,
wrong-service, wrong-role, malformed, or invalid-signature bindings. There is no
default key, fallback verifier, or bypass. Private keys are test-fixture data
only; this stage adds no production key storage or key retrieval.

Identical logical retries produce the same event ID and hashes when content is
identical. Same ID with different content is an integrity conflict for the
future consumer; it is not overwritten or silently deduplicated.

## 9. Compatibility policy

- Major version and event name are explicit and never inferred.
- There are no aliases for legacy Quad Repo names.
- Unknown events and payloads fail validation; a future consumer may quarantine
  raw transport evidence, but cannot assign semantic authority to it.
- Additive fields are not accepted in v1 because all models forbid extras.
- Any compatible extension requires a reviewed contract version and fixtures.
- Correction, supersession, and invalidation are append-only references; they
  never mutate an earlier envelope.

## 10. Security remediation closure

The initial security diff scan
`1ca4fb0d-5982-47a3-99ac-a8905e43ada8` reported finding
`csf_ddb609272cd160150e255020`: recomputable hashes did not authenticate the
WOLF15 producer. The owner authorized a local contract-only remediation.

The remediation re-scan `e01e3c8a-41c4-4613-8441-837410c0b151`, bound to
working-tree snapshot
`codex-security-snapshot/v1:sha256:c1ff51ccdeb4128cea0cd312a744838bf59c69ce33bd57af6334f2948ea27551`,
completed with zero reportable findings. The original reproducer now produces:

```text
STRUCTURAL_STATUS = UNTRUSTED
FORGED_ACCEPTED   = false
REJECTION_REASON  = producer signature is invalid
```

The legitimate control produces `VALID_SIGNATURE=ACCEPTED`. Unknown, revoked,
wrong-domain, wrong-service, wrong-role, invalid-signature, and known event-ID
conflict cases fail closed. Therefore the prior finding state is
`CLOSED_VERIFIED` for this exact WLA-01 snapshot. This is not a runtime or
production-readiness claim.

## 11. Definition of Done

WLA-01 may be submitted for human decision only when:

- [x] the charter, contract, fixtures, tests, receipt, and decision packet are
  present on the isolated branch;
- [x] positive fixtures cover Alpha decision/abstention plus all five Outcome
  Evidence variants, deterministic retry, stream chaining, and ancestry;
- [x] negative fixtures cover unknown type, extra/unknown nested fields,
  authority/event mismatch, safety escalation, consumer timestamps, hash
  conflict, recomputed-hash forgery, unknown key, wrong signature domain,
  invalid signature, clock inversion, and unavailable identity relabeled
  `VALID`;
- [x] authentication tests prove valid Ed25519 acceptance and fail-closed
  rejection of unknown/revoked/wrong-domain/wrong-role keys, invalid signatures,
  forged payloads, and same event ID with different content;
- [x] Ruff and Pyright pass for the WLA-01 contract and fixture generator;
- [x] all WLA-01 contract tests pass with no network, database, broker, EA, or
  runtime operation;
- [x] a forbidden-scope scan finds no runtime registration, migration,
  deployment, credential, storage, or transport mutation; and
- [ ] the owner records an explicit WLA-01 verdict bound to exact hashes.

Test success alone does not set WLA-01 to `PASS`. Until the final human decision:

```text
WLA_01              = IN_PROGRESS
WLA_01_AUTHORIZED   = TRUE
AUTHORIZED_SCOPE    = CONTRACT_ONLY
RUNTIME_MUTATION    = NONE
WLA_02              = NOT_STARTED
```
