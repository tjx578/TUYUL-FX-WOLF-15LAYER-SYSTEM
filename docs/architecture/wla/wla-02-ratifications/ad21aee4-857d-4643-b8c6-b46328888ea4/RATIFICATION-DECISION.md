# WLA-02 Golden Corpus Ratification Decision

Decision ID: `WLA02-DEC-20260824-001`

Ratification ID: `ad21aee4-857d-4643-b8c6-b46328888ea4`

Packet ID: `WLA02-RP-20260824-001`

Exception ID: `WLA02-EXC-001`

Evaluated at UTC: `2026-08-24T15:24:37.934Z`

Canonical verdict: `PASS`

## 1. Authenticated owner evidence

The owner attestation was committed through GitHub Web UI and independently
checked against GitHub commit metadata:

```text
SIGNED_ATTESTATION_COMMIT = fd63f54fda29c243cfb3879e18e8c121f91c3b1d
COMMIT_PARENT             = 64b8bf3f1e8e16f105275e4fdbd1e1479e3c759f
GITHUB_VERIFIED           = TRUE
VERIFICATION_REASON       = valid
AUTHENTICATED_PRINCIPAL   = tjx578
AUTHENTICATED_PRINCIPAL_ID= 221953664
COMMITTER                 = web-flow
SIGNED_AT_UTC             = 2026-08-24T15:22:03Z
OWNER_DECIDED_AT_UTC      = 2026-08-24T15:17:44.948Z
```

The signed commit postdates the owner decision and changes only
`OWNER-ATTESTATION.yaml`, adding the explicit Web UI confirmation. Its signed
tree retains the complete packet and attestation.

## 2. Binding validation

```text
TARGET_REPOSITORY         = tjx578/TUYUL-FX-WOLF-15LAYER-SYSTEM
TARGET_BRANCH             = codex/wla-01-contract-only
TARGET_BASE_SHA           = 22ee9774930d2bf5d09a32851098a8dba8918167
REQUESTED_SCOPE           = WLA-02_GOLDEN_CORPUS_ONLY
SUBMITTED_VERDICT         = APPROVED
CONDITIONS                = []
CONDITIONS_SHA256         = 4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945
PACKET_SHA256_EXPECTED    = 56bf3a4f3dc1c7b2b125747d78d13add551c838391af63fc3615c948da39d9d3
PACKET_SHA256_COMPUTED    = 56bf3a4f3dc1c7b2b125747d78d13add551c838391af63fc3615c948da39d9d3
PACKET_HASH_MATCH         = TRUE
IDENTITY_MATCH            = TRUE
SCOPE_DRIFT               = FALSE
```

## 3. Decision

All fail-closed authentication, identity, timing, hash, condition, and scope
checks passed. The single-owner bootstrap exception is therefore activated for
one bounded purpose:

```text
WLA_02_GOVERNANCE_DECISION = PASS
WLA_02_AUTHORIZED           = TRUE
AUTHORIZED_SCOPE            = WLA-02_GOLDEN_CORPUS_ONLY
WLA_02_IMPLEMENTATION       = NOT_STARTED
WLA_02_DOD                  = NOT_EVALUATED
```

Authorization is limited to deterministic offline decision/outcome mappers,
the offline envelope fixture factory, golden fixtures, strict realized versus
counterfactual separation, the future-leakage canary, bitemporal replay,
golden-hash tests, correction-lineage tests, and the pure schemas and
documentation needed to prove those artifacts.

## 4. Continuing prohibitions

This decision does not authorize runtime registration or imports, a
transactional outbox, database mutation, dispatcher or network delivery,
broker/EA or execution access, deployment, production credentials, repository
creation, modification or promotion of `main`, WLA-03, Gate P0-A, or learner,
Challenger, or SHADOW self-promotion.

```text
RUNTIME_MUTATION          = NONE
DATABASE_OR_OUTBOX        = FORBIDDEN
NETWORK_OR_DISPATCHER     = FORBIDDEN
BROKER_OR_EA              = FORBIDDEN
DEPLOYMENT                = FORBIDDEN
NEW_REPOSITORY            = FORBIDDEN
MAIN_PROMOTION            = FORBIDDEN
WLA_03_AUTHORIZED         = FALSE
GATE_P0_A                 = NOT_EVALUATED
```

## 5. Lifecycle

`WLA02-EXC-001` is single-use and non-reusable. It expires when WLA-02 reaches
its Definition of Done or immediately upon any proposed scope expansion.
Neither expiry nor completion carries authority forward to WLA-03, runtime,
deployment, repository creation, or Gate P0-A.

The `PENDING_VERIFIED_SIGNATURE` value inside the immutable owner attestation
is the pre-evaluation snapshot. This append-only decision is the later
canonical governance verdict.
