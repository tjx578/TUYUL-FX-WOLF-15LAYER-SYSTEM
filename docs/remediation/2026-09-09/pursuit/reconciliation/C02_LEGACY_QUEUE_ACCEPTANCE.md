# C02 actual legacy queue acceptance

P1 remains INCOMPLETE / HOLD; no milestone closure is asserted.

## Verified predecessor candidate

HEAD468828268b4ad07bd75081188714f9312b30842e has successful CI34407659167, Security34407659280 and Docs34407659157.
Tested merge e0a1b7a919610789a5ded6180a4802624ef98850 has identical Git tree.
Independent audit matched41 runtime paths and69 exact-reviewed Security findings against candidate bytes.
Separate verified lanes:10500 main JUnit cases;29 benchmark identities;4 mode-owner;2 drain;100 dedicated PostgreSQL cases across seven receipts;7 built-engine scenarios. All scoped JUnit lanes have zero failure/error/skip. Counts are not summed.
API artifacts contain10 built-image cases and actual API readiness200→causal503→nonzero master exit.

Evidence: D:/WOLF15-work/master-remediation-20260909/runtime-46882826/independent-runtime-security-audit.json, independent-artifact-audit.json, and consumer-verification-46882826/verified-summary.json.

## New required acceptance

The existing engine/trade Docker acceptance now requires:
1. Actual legacy module with disabled plane exits0 without consumer group or recording-sink dispatch.
2. Incoherent enabled legacy/disabled execution exits nonzero with precise reason.
3. Simultaneous legacy/signed bridge exits nonzero with precise conflict.
4. Actual constructor with disabled plane rejects before executor creation.
5. Valid synthetic Redis queue payload traverses the actual module, worker and BrokerExecutor to a loopback recording sink exactly once, then ACKs with zero pending.

Negative cases require unchanged Redis and public PostgreSQL rows. Positive case validates exact request identity/body, retained original stream entry, delivered ID, ACK and unchanged public rows.
This is TEST_ONLY transport containment, not broker acceptance or strategy/risk authority.

## Isolation and review

Reuse the verified internal Docker network, marked disposable PostgreSQL and dedicated empty Redis logical DB1. DB0 role heartbeats are not compared across this fixture because legitimate TTL expiration would confound state checks.
Remove proxy and alternate Redis connection variables; bind both parent and child to cache DB1 and HTTP loopback. Only the positive-control subprocess enables execution and legacy flags; all other execution-plane flags remain off.
Finally reap processes, stop/join recording sink, delete only the fixture queue and verify restored empty DB1. Partial case progress remains in failure receipt.
Outer660-second process budget covers existing role deadlines plus four negative subprocesses and positive control; individual deadlines remain bounded.
Source hashes for worker, executor, flags, queue contract and harness are compared between child image and candidate.

Independent agent designed and implemented the first patch; integrator reviewed payload/ACK contract, removed duplicate source entries, separated Redis DB1, preserved failure stages and reconciled deadlines.

## Validation and remaining work

Ruff check and format passed. Local reconcile-legacy-queue-a1:55 passed, no failure/error/skip, source unchanged, isolated environment.
Docker acceptance for this new patch: NOT_EXECUTED locally; required Linux CI must execute it before closure.
Preserve predecessor receipts; new source requires fresh checks.
C05 still requires independent-review controls and a named Production reviewer. The prepared provider proposal has not been applied.
