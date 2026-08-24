# WLA-02 Golden Corpus Ratification Packet

Packet ID: `WLA02-RP-20260824-001`

Ratification ID: `ad21aee4-857d-4643-b8c6-b46328888ea4`

Exception ID: `WLA02-EXC-001`

Governance mode: `SINGLE_OWNER_BOOTSTRAP`

Status: `AWAITING_VERIFIED_OWNER_SIGNATURE`

Target repository: `tjx578/TUYUL-FX-WOLF-15LAYER-SYSTEM`

Target branch: `codex/wla-01-contract-only`

Target base SHA: `22ee9774930d2bf5d09a32851098a8dba8918167`

Requested scope: `WLA-02_GOLDEN_CORPUS_ONLY`

## 1. Preconditions

The target base contains the append-only WLA-01 completion receipt and records:

```text
WLA_00_RATIFICATION         = PASS
WLA_01_GOVERNANCE_DECISION = PASS
WLA_01_IMPLEMENTATION      = PASS
WLA_01_DOD                 = PASS
WLA00_EXC_001              = EXPIRED_CONSUMED
WLA_02                     = NOT_STARTED
WLA_02_AUTHORIZED          = FALSE
```

WLA-01 completion makes WLA-02 eligible for human consideration. It does not
carry authorization forward automatically.

## 2. Authorized deliverables

If this packet receives a valid GitHub Verified owner attestation, WLA-02 is
limited to pure golden-corpus artifacts and tests for:

1. a deterministic decision mapper;
2. a deterministic outcome-evidence mapper;
3. an offline `AlphaLearningEnvelopeV1` fixture factory;
4. deterministic golden fixtures;
5. strict realized-versus-counterfactual separation;
6. a future-leakage canary that fails closed;
7. bitemporal replay with explicit event-time and knowledge-time boundaries;
8. stable golden-hash tests; and
9. append-only correction-lineage tests.

Documentation, pure schemas, local deterministic generators, and local tests
needed to prove these deliverables are included. Production private keys are
not included; any signing key used by a fixture must remain test-only.

## 3. Continuing prohibitions

This exception does not authorize:

- runtime registration or runtime imports;
- a transactional outbox, queue, scheduler, cursor, or dispatcher;
- database schema, role, migration, or data mutation;
- network delivery or external service access;
- broker, EA, order-router, risk-reservation, advisory, or execution access;
- deployment, production mutation, or production credentials;
- creation of a repository or learning service;
- modification or promotion of `main`;
- WLA-03;
- Gate P0-A certification; or
- learner, Challenger, or SHADOW self-promotion.

## 4. Corpus authority rules

- Golden corpus artifacts are offline test evidence, not runtime events.
- Realized evidence and counterfactual evidence must use different explicit
  discriminators and must never be merged into one authoritative label.
- A mapper cannot create source authority that is absent from its input.
- Knowledge-time data later than the replay cutoff must trigger the
  future-leakage canary and fail closed.
- Corrections are append-only lineage entries; no earlier fixture is rewritten.
- Repeated generation from identical pinned inputs must produce identical bytes
  and hashes.
- No fixture, mapper, or replay result can issue a verdict, mutate WOLF15,
  execute, or self-promote.

## 5. Single-owner exception

`WLA02-EXC-001` acknowledges that the constitutional owner currently performs
the ARO, WAO, JDS, MRR, and SEC functions without false claims of independent
concurrence or backup availability.

The exception is single-use, non-reusable, and expires at the earlier of:

1. WLA-02 Definition of Done completion; or
2. any proposed scope expansion.

Expiry preserves historical evidence but grants no authority to WLA-03,
runtime, deployment, repository creation, or Gate P0-A.

## 6. Authentication and evaluation

The owner attestation must bind:

```text
packet_id
ratification_id
exception_id
packet_sha256
target_base_sha
scope
verdict
conditions_sha256
owner identity and GitHub numeric ID
decision timestamp
```

The signing commit must be created through GitHub Web UI by `tjx578`, report
`verified=true` and `reason=valid`, retain this packet and the complete owner
attestation in its signed tree, and postdate the owner decision.

Evaluation is fail-closed:

```text
VERIFIED OWNER ATTESTATION + APPROVED + CONDITIONS=[] + ALL HASHES MATCH
  -> WLA_02_GOVERNANCE_DECISION=PASS
  -> WLA_02_AUTHORIZED=TRUE
  -> AUTHORIZED_SCOPE=WLA-02_GOLDEN_CORPUS_ONLY

MISSING/INVALID/REVOKED SIGNATURE, IDENTITY OR HASH MISMATCH, OR SCOPE DRIFT
  -> BLOCKED
  -> WLA_02_AUTHORIZED=FALSE
```

## 7. Current status

Until the signature is validated:

```text
NEXT_GATE                  = HUMAN_RATIFICATION_WLA_02
WLA_02_GOVERNANCE_DECISION = NOT_EVALUATED
WLA_02                      = NOT_STARTED
WLA_02_AUTHORIZED           = FALSE
RUNTIME_MUTATION            = NONE
NEW_REPOSITORY              = FORBIDDEN
MAIN_PROMOTION              = FORBIDDEN
GATE_P0_A                   = NOT_EVALUATED
```
