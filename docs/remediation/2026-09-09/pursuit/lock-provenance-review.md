# Sizing-to-lock provenance checkpoint

**SOURCE_FIX_LOCAL_PASS / INCOMPLETE / HOLD.** No canonical action or milestone
closes. This continues K07 on the existing risk sizing and authorization path.

Approved `PositionRiskResult` now carries a fingerprint of the complete supplied
`CampaignRiskLock`: account, campaign, lock time, balance basis, risk percentage,
1R and campaign cap. Authorization recomputes that fingerprint against its current
lock. A missing or different fingerprint cannot authorize, even when budget and
actual risk are numerically identical. Denied sizing results keep their existing
rejection behavior; contradictory approval reasons remain invalid.

The fingerprint encodes Decimal values as exact rational pairs and normalizes the
aware lock clock to UTC. A database's trailing-zero scale changes therefore do not
create a different identity. A naive lock clock is rejected explicitly. The test
lock fixture uses a fixed aware timestamp so tests refer to the same lock, rather
than constructing unrelated clock identities on each helper invocation.

This is an identity check, not a signature or external proof. The repository must
still obtain its lock and broker evidence from its trusted transaction. The result
does not yet bind broker snapshot, symbol, tradeplan or candidate identity. Those
remain separate integration work; a fingerprint is not sufficient to accept a
caller-forged risk result.

The existing reservation repository is the sole non-test caller found for sizing.
It receives the fingerprint automatically from the sizing function and checks it
through `authorize_campaign_risk`; no new runtime switch or database migration is
required by this source change. Actual database reload/recovery was not executed.

| Acceptance exercised | Local outcome |
| --- | --- |
| Equal-budget result from another account or campaign | Rejected |
| Same IDs/budget but another lock time or cap | Rejected |
| Approved legacy result without fingerprint | Rejected |
| Equivalent Decimal values at database scale | Same identity; valid result accepted |
| Naive lock clock | Explicit RISK_STATE_INVALID |

Final `rp3`: **41 passed, zero failures/errors/skips**, with exact JUnit identities
matching collection. Seven new cases supplement overlapping risk and reservation
tests; no totals are added to older suites. Ruff lint and format pass for all
application source (1,409 files). `rp1` and `rp2` remain intermediate evidence;
`rp3` binds the final formatted source. Independent agent review remains unavailable
after the prior quota failure; this checkpoint records self-review.

Evidence: `evidence/lock-provenance-validation.json`, `rp3-receipt.json`, `rp3.xml`,
and `lock-provenance-source.diff`. Historical receipts retain their original
source identity. README and canonical register are unchanged. Active DEMO profile,
PostgreSQL/Linux acceptance, broker integration and publication blockers remain
open. No push, main merge, deployment, production migration or broker action ran.
