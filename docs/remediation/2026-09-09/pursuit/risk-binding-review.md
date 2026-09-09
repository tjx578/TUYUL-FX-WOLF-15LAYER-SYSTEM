# Existing risk authorization repair

Verdict: **SOURCE_FIX_LOCAL_PASS / INCOMPLETE / HOLD**. No canonical action or
milestone is closed. This slice repairs the existing risk authorization path;
it does not create another TEST_ONLY strategy solver or select an active profile.

`storage/strategy_5scr_risk_reservation_repository.py` sizes a position and calls
`authorize_campaign_risk` before writing the durable reservation. Previously,
authorization trusted the sizing result's allowed flag and checked aggregate
campaign/account caps without rechecking its budget against the current lock.
A result sized with a 60-unit budget could be accepted against a 50-unit lock
because the aggregate 100-unit caps still had room. An inconsistent result with
`allowed=False` and an approval reason could also return that approval reason.

The repair requires a matching risk budget and entry-role approval reason,
positive finite sizing fields, consistent volume/loss/actual-risk arithmetic,
and actual risk no greater than the current lock's 1R. Nonfinite or negative
ledger totals return an explicit invalid-state rejection. Legitimate denied
sizing reasons continue to propagate. Valid parent and child policy behavior
is retained by the regression suite.

The repository no longer converts PostgreSQL numeric totals to float before
authorization. Campaign and account cap comparisons use exact rational
arithmetic, preventing an excess from disappearing through floating-point or
Decimal-context rounding. This is a source change on the existing caller, not
evidence that it has been deployed or exercised on PostgreSQL.

| Reproduction / expected outcome | Local result |
| --- | --- |
| Different sizing budget cannot use aggregate capacity of the current lock | Rejected |
| A matching-budget but over-1R result is rechecked | ACTUAL_EXCEEDS_1R |
| Contradictory approval flag/reason, role, loss or amount cannot authorize | RISK_STATE_INVALID |
| NaN/infinite/negative ledger values do not approve or escape as arithmetic errors | RISK_STATE_INVALID |
| Decimal amount just above an aggregate cap remains above it | Correct campaign/account cap rejection |
| Valid result under the current lock remains accepted | Approved |

Baseline `rb1` reproduced 11 failures before the source repair. Final `rb4`
passed **34 tests, zero failures/errors/skips**; exact JUnit identities match
collection. `rb2` initially passed all tests but the exact-ID check rejected its
receipt: an existing test generated a UUID independently during collection and
execution. The tamper fixture now uses a fixed UUID; `rb3` and final formatted
`rb4` retain deterministic identities. Ruff lint and format pass for all
application source (1,409 files).
Evidence includes all runs and `risk-binding-source.diff`. The new suite is
not added to earlier test totals. Independent review remains unavailable after
the prior agent quota failure; review here is self-review.

The sizing result still does not carry full account/campaign provenance. Equal
budget does not prove identical origin; that lineage remains an open dependency.
The existing caller constructs sizing from its current lock, but a broader
adapter must bind identity explicitly. Historical policy defaults are unchanged
and are not adopted as the active DEMO profile. No currency conversion, live
broker loss calculation, ledger concurrency or recovery acceptance is claimed.

K06's complete target-family and active policy binding remain open. K07 now has
a concrete existing-source repair; R01/R02 and runtime milestones remain open.
The PostgreSQL, CI, DEMO and publication blockers retain their prior scope.
README and canonical register remain unchanged. No push, merge, deployment,
production migration or broker operation occurred.
