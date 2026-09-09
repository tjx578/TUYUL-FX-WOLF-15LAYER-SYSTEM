# Reservation snapshot and candidate row binding

**SOURCE_FIX_LOCAL_PASS / INCOMPLETE / HOLD.** No canonical action or milestone
closes. This K07 slice changes the existing reservation repository and USD risk
snapshot validation. It does not activate a new execution mode or risk profile.

The repository previously parsed snapshot payloads without comparing their ID
and capture clock to the selected database row. It also fetched candidate columns
but checked only the payload hash and requested TradePlan identity. A valid hash
of a payload alone did not establish agreement with the row's remaining metadata.

`reserve_parent` now uses `_snapshot_from_row` to compare the snapshot ID and
capture clock, and `_candidate_from_row` to compare TradePlan ID, the existing
lifecycle/campaign mapping, symbol, direction and decision clock. Existing
candidate non-execution and payload-hash gates remain. The SQL snapshot selection
now returns `captured_at` explicitly. Current integration seed code was inspected
and writes that column from the same snapshot clock; actual PostgreSQL execution
remains unperformed.

The existing risk primitives calculate amounts named and treated as USD. Their
snapshot gate now rejects non-USD accounts with
`RISK_ACCOUNT_CURRENCY_UNSUPPORTED` rather than interpreting those balances and
loss values as USD. This does not authorize a conversion rate, select the user's
DEMO account currency, or replace the required active account-risk profile.

| Acceptance exercised | Local outcome |
| --- | --- |
| Matching stored snapshot/candidate rows | Accepted by parsing/binding helpers |
| Snapshot ID or captured-at drift | Conflict rejection |
| Candidate column drift despite a valid payload hash | Conflict rejection for all five fields |
| JPY, EUR or USC snapshot in USD risk primitives | Explicit unsupported-currency rejection |

Final `rs1`: **52 passed, zero failures/errors/skips**, exact JUnit identities match
collection. Eleven new cases supplement 41 overlapping risk/reservation cases.
The tests call the same helpers now used by `reserve_parent`, but do not prove
transaction behavior, database constraints or live snapshot authenticity. Ruff
lint and format pass for all application source (1,409 files). Independent agent
review remains unavailable after the earlier quota failure; this is self-review.

Evidence: `evidence/reservation-row-validation.json`, `rs1-receipt.json`, `rs1.xml`,
and `reservation-row-source.diff`. README and canonical register are unchanged.
The V1 schema remains V1: no regex or string rewriting admits a v3.1/shadow plan
into the legacy schema. The v3.1 adapter, active policy, database concurrency and
recovery, broker reconciliation and natural DEMO remain open. No push, merge,
deployment, production migration or broker operation occurred.
