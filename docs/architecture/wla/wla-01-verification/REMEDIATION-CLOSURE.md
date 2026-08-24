# WLA-01 Producer Authentication Remediation Closure

Closure ID: `WLA01-CLOSURE-20260824-001`

State: `CLOSED_VERIFIED`

Evidence boundary: the exact local WLA-01 contract-only working-tree snapshot
identified by security digest
`codex-security-snapshot/v1:sha256:c1ff51ccdeb4128cea0cd312a744838bf59c69ce33bd57af6334f2948ea27551`.
This closure is not evidence of runtime, deployment, production-key, database,
broker, EA, Journal, or learning-system readiness.

## Original vulnerable path

The initial contract treated matching SHA-256 payload and envelope hashes as
sufficient for acceptance. An attacker able to edit a serialized envelope could
change the payload, recompute both unkeyed hashes, and obtain
`FORGED_ACCEPTED=true`. Hash integrity alone did not authenticate WOLF15 as the
producer.

- Initial scan: `1ca4fb0d-5982-47a3-99ac-a8905e43ada8`
- Finding: `csf_ddb609272cd160150e255020`
- Occurrence: `occ_0f4d233d0a20e78bdff11d40`

## Enforced invariant

Structural parsing can produce only an opaque `UNTRUSTED` object. The sole
public transition to `ACCEPTED` verifies a domain-separated Ed25519 signature
against an explicit key binding. The signed canonical unsigned envelope binds
event ID, event type, schema/version, source identity and service, producer
role, key ID, payload, payload hash, and envelope hash.

The verifier requires an explicit producer-key registry and known-event hash
view. It rejects unknown or revoked keys, algorithm/domain/service/role
mismatch, malformed key or signature bytes, invalid signatures, and same-ID
content conflicts. No default key, fallback verifier, acceptance constructor,
network key retrieval, or production private-key storage exists.

## Verification proof

The original exploit no longer reproduces:

```text
STRUCTURAL_STATUS = UNTRUSTED
FORGED_ACCEPTED   = false
REJECTION_REASON  = producer signature is invalid
```

The legitimate control remains available:

```text
UNAUTHENTICATED_STATUS = UNTRUSTED
VALID_SIGNATURE        = ACCEPTED
```

The focused suite passed 33 tests, including forged payload plus recomputed
hashes, unknown and revoked keys, wrong domain, wrong source service, wrong
role, invalid signature, and a validly signed same-ID content conflict. The 22
prior-art observer tests also passed. Ruff, Pyright, Draft 2020-12 schema
validation, deterministic fixture generation, and dependency-range validation
passed.

Security re-scan `e01e3c8a-41c4-4613-8441-837410c0b151` completed with complete
coverage and zero reportable findings. The scan consumed 2,275,768 total tokens,
including 2,270,489 input tokens and 2,254,336 cached input tokens.

`pip check` still reports unrelated, pre-existing OpenTelemetry version
conflicts in the local environment. The WLA-01 dependency, `cryptography
46.0.7`, satisfies its declared `>=46,<47` range. This advisory is not promoted
to a WLA-01 PASS and was not modified within this remediation.

## Remaining boundary

This closure makes the contract evidence eligible for owner review. It does not
set WLA-01 to PASS. WLA-01 remains `AWAITING_HUMAN_DECISION`; WLA-02 remains
`NOT_STARTED`; runtime mutation remains `NONE`.
