# WLA-01 Contract-Only Decision

Decision record ID: `WLA01-RD-20260824-001`

Owner decision ID: `df07182d-215c-4c49-ae49-f3c94d0c0951`

Canonical verdict: `PASS`

Effective at: `2026-08-24T14:45:32Z`

Validated at: `2026-08-24T14:46:58.860Z`

Governance mode: `SINGLE_OWNER_BOOTSTRAP`

Exception: `WLA00-EXC-001`

This append-only decision record validates the constitutional owner's signed
WLA-01 attestation. It closes only the contract-only stage reviewed at the
bound evidence commit. It grants no runtime authority and does not authorize
WLA-02.

## 1. Bound evidence

| Evidence | Validated value |
| --- | --- |
| Decision packet | `WLA01-DECISION-PACKET-20260824-001` |
| WOLF15 exact base SHA | `7ff2a9194b22e185b35dc61574c61628ba404939` |
| WLA-01 evidence commit | `87a3ba3338d2ff66b543051b8c8d8e76fdc247e1` |
| Core bundle SHA-256 | `6704d174f55e9b03acafec22e51bc1cef187544f6ecc550d923c93139d040fd5` |
| Fixture tree SHA-256 | `6a86689d0ca96cf54c1d03d51062ac5706c2f0e1f7cee1ee404b704f455dbcce` |
| Security scan | `e01e3c8a-41c4-4613-8441-837410c0b151` |
| Security snapshot | `codex-security-snapshot/v1:sha256:c1ff51ccdeb4128cea0cd312a744838bf59c69ce33bd57af6334f2948ea27551` |
| Security finding state | `CLOSED_VERIFIED` |
| Submitted verdict | `APPROVED` |
| Conditions | `[]` |
| Conditions SHA-256 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| Owner decision time | `2026-08-24T14:42:27.780Z` |
| Verified attestation commit | [`a66cc3d068fe44296e301b3d4f4d661f8e8886da`](https://github.com/tjx578/TUYUL-FX-WOLF-15LAYER-SYSTEM/commit/a66cc3d068fe44296e301b3d4f4d661f8e8886da) |
| GitHub verification | `verified=true`; `reason=valid`; `verified_at=2026-08-24T14:45:32Z` |
| Authenticated principal | `tjx578`; numeric ID `221953664` |
| Commit author | `tjx578` |
| Committer/trust anchor | GitHub `web-flow` |
| Signed attestation path | `OWNER-ATTESTATION.yaml` in this directory |

## 2. Validation sequence

| Check | Result |
| --- | --- |
| Evidence commit is the exact reviewed WLA-01 target | `PASS` |
| Core and fixture bundle hashes match the decision packet | `PASS` |
| Security re-scan is complete with zero reportable findings | `PASS` |
| Prior producer-authentication finding is closed | `PASS` |
| Verdict is APPROVED with empty conditions | `PASS` |
| RFC 8785 empty-conditions hash matches | `PASS` |
| GitHub subject and numeric identity match | `PASS` |
| GitHub reports the attestation signature valid | `PASS` |
| Signature timestamp postdates the owner decision | `PASS` |
| Signed tree retains the exact attestation tuple | `PASS` |
| Independent concurrence is not falsely claimed | `PASS_WITH_RESTRICTION` |
| Backup assignment is not falsely claimed | `PASS_WITH_RESTRICTION` |
| Runtime, repository, deployment, and WLA-02 authority remain absent | `PASS` |

GitHub's commit API is the validity and revocation reference for the owner
signature. If the signature becomes invalid, the account binding changes, or
any bound evidence hash changes, this decision returns to fail-closed pending
new evaluation.

## 3. Effective status

```text
GOVERNANCE_MODE       = SINGLE_OWNER_BOOTSTRAP
WLA_00_RATIFICATION   = PASS
WLA_01                = PASS
WLA_01_SCOPE          = CONTRACT_ONLY
WLA00_EXC_001         = EXPIRED_CONSUMED
WLA_02                = NOT_STARTED
WLA_02_AUTHORIZED     = FALSE
RUNTIME_MUTATION      = FORBIDDEN
NEW_REPOSITORY        = FORBIDDEN
GATE_P0_A             = NOT_EVALUATED
```

WLA-01 PASS means only that the charter, RD-001 through RD-008 decisions,
`AlphaLearningEnvelopeV1` schema and implementation, deterministic fixtures,
pure contract tests, and producer-authentication remediation satisfied the
reviewed contract-only gates.

It does not mean the envelope is registered, transported, persisted, deployed,
or accepted by a runtime consumer.

## 4. Continuing prohibitions

This decision does not authorize:

- WLA-02 corpus work;
- runtime registration;
- database migration or outbox activation;
- dispatcher, broker, or EA access;
- deployment or production mutation;
- advisory activation or execution authority;
- creation of a learning repository;
- Gate P0-A certification; or
- learner, Challenger, or SHADOW self-promotion.

## 5. Exception expiry and next gate

`WLA00-EXC-001` was single-use and expired when WLA-01 completed. Historical
WLA-00 and WLA-01 evidence remains valid, but no authorization carries forward
to WLA-02.

Before WLA-02 begins, the constitutional owner must perform a new governance
evaluation that explicitly defines the corpus-only scope, evidence boundary,
repository impact, security gates, and renewed single-owner exception if
separation of duties is still unavailable.

This decision record lives on the evidence branch. Promotion or merge into
another branch requires separate explicit authorization and does not broaden
its scope.
