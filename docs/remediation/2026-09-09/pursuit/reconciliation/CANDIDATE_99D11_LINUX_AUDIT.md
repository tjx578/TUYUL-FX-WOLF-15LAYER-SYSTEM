# Candidate 99d11 Linux artifact audit

Status: P1 INCOMPLETE / HOLD; 0/6 milestones DONE.

Candidate HEAD: 99d11b8cecf03abe70c9796e37ec08a61d3ffb2b.
PR: #456, codex/p1-c03-runtime-closure-20260910.
CI run 34405973077 completed SUCCESS. Docs run 34405973076 SUCCESS.
Security run 34405973152 FAILURE in Secret leak scan; required Security Gate remains failed.

## Source binding

Actual CI checkout: 4ff0787e03902c4f5b489895cc6f1e2150242684.
Parents: bedb7d05322c78dde85e7dc88e9171fcd84bb849 and candidate HEAD.
Git diff between candidate and tested merge has no tree differences.
Independent artifact audit compared all 13 engine and 13 performance source hashes against exact Git bytes at both revisions.

## Expected versus actual

| Scope | Expected | Actual inspected evidence |
| --- | --- | --- |
| Built engine | Seven named cases, no pool close with live writer | bootstrap_failure, graceful, exception, returned, cancelled, restart, resistant all passed; exact set/count verified |
| Performance | 29 exact benchmark identities, no skip, thresholds active, no coverage | All 29 passed; bound manifest and verifier matched XML identities and receipt hash; unchanged source before/after |
| Main Python JUnit | No failure/error/skip | 10500 cases, zero failure/error/skip |
| Mode owner lane | Four cases | 4 passed, zero failure/error/skip |
| Runtime drain lane | Two cases | 2 passed, zero failure/error/skip |
| Dedicated PostgreSQL | Exact inventory and artifact/source hash agreement | Seven receipts verified: 45 runtime, 7 producer, 17 consumer, 1 consumer-role, 12 Transaction A, 8 capacity, 10 candidate revision; 100 scoped cases, no failure/error/skip |
| Supported upgrade | Disposable baseline05 to head with ledger preserved | Receipt accepted, both exits zero, actual head20260909_07, equal row hashes, PostgreSQL160015 |
| Security | All findings reviewed or absent | Three REVIEW_REQUIRED findings: two Railway selectors in governance test and one Postgres redaction fixture extraction |
| C05 controls | Independent PR and Production review controls | Live read: approvals0, last-push approval false, Production admin bypass true, no required-reviewer rule |

Suite counts are separate scopes, not an aggregate total. No production or broker authority follows from these results. Built-engine dependencies and analysis cycle are injected TEST_ONLY fixtures.

## Stored evidence

Outside repository, preserved original downloads and verification output:
- D:/WOLF15-work/master-remediation-20260909/runtime-99d11b8/independent-artifact-audit.json
- D:/WOLF15-work/master-remediation-20260909/python-suite-99d11b8/
- D:/WOLF15-work/master-remediation-20260909/consumer-verification-99d11b8/verified-summary.json
- D:/WOLF15-work/master-remediation-20260909/security-99d11b8/receipt.json
- D:/WOLF15-work/master-remediation-20260909/c05-proposal-99d11b8.json

Original failed Security receipt is retained. Independent agent and integrator review reconstructed all three exact finding hashes from source. Two are noncredential resource selectors; the Postgres finding is the mocked URL prefix through host:port, while the existing exception bound the full URL. Three narrow tuples were added without changing scanner behavior. No credential validation endpoints used. Local reconcile-secret-review-a1: 24 passed, zero failure/error/skip, source unchanged. Fresh remote Security remains required for the new commit.
C05 proposal is prepared, NOT_APPLIED. Reviewer username/team identity is requested. Preserve source review requirements.

## Remaining closure work

- Resolve Security finding review, then require fresh checks for any changed candidate.
- Apply authorized, fully bound C05 configuration correction after independent reviewer identity is available; validate actual provider responses.
- Complete remaining runtime/image receipt audit beyond the engine/performance scopes verified here.
- C02 actual legacy worker/queue to recording sink coverage remains incomplete according to independent agent review.
- Reconcile C01-C06 against canonical register before P1 closure. Do not add DEMO strategy/broker prerequisites to P1, and do not infer DEMO completion from P1 evidence.
