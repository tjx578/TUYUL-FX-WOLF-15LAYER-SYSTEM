# Strategy 5S-CR runtime authority promotion (SSOT v3.1)

Machine-readable record: [strategy-5scr-runtime-authority.json](strategy-5scr-runtime-authority.json).
Final approver: the owner. **The merge of this record into `main` is the activation event.**
Until that merge, the previous authority below remains the runtime authority.

## 1. Authority transition

| | Document | Identity | Status after merge |
|---|---|---|---|
| Previous | [strategy-5scr-final.md](../strategy/strategy-5scr-final.md) | rule `5scr.final.2026-07-19` | `SUPERSEDED_LEGACY` |
| New | [selected-ssot-v3.1.md](../remediation/2026-09-09/source-binding/selected-ssot-v3.1.md) | sha256 `6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902` | `APPROVED_RUNTIME_AUTHORITY` |

Neither document's bytes change.
- The SSOT copy is byte-exact (`-text`), and its sha256 is pinned by `CandidateHandoffV31.selected_ssot_hash` and `SELECTED_SSOT_SHA256`.
- Its internal front-matter (`PROPOSED_CANONICAL`, `runtime_authority: NONE_UNTIL_APPROVED`) is superseded by this record. It is not edited.
- On any conflict between the two documents, this record decides which one is authoritative.

There is exactly one authority at any time: `dual_authority = false`.

## 2. Runtime family

SSOT v3.1 is implemented natively by the **V31** family: `CandidateHandoffV31`, `candidate_revision_v31`, `capacity_v31` and `transaction_a_v31`. That family is already hash-bound to this SSOT.

The **V2** family (`context_epoch_v1` → … → `candidate_c2_shadow_v2`) remains a legacy, non-authoritative line.

A V2 → V31 adapter is **prohibited** unless a future authority decision changes the contract. The 2026-09-19 audit found that V31 requires fields V2 never produces: an analysis admission id/class, a pressure hypothesis id, `net_rr`, and ordered-proof / context-route receipts. A translation layer would therefore have to invent strategy or risk authority.

## 3. What promotion does not do

Merging this record does **not** perform or enable any of the following:
- deploy
- execution, enqueue or ARM
- order submission
- Algo Trading
- any feature flag
- any broker effect

`AUTHORITY_PROMOTION ≠ RUNTIME_EXECUTION_ENABLEMENT`. Every runtime enablement needs its own qualified change and owner authorization.

## 4. Known implementation gaps (approval ≠ implementation closure)

| ID | Gap |
|---|---|
| G1 | Raw admission is one global ordered stream. A cross-symbol event finalizes another symbol's block, so pair activity is coupled. |
| G1b | A direction change finalizes the block (direction coupling; remediation 2026-09-09 P2). |
| V31_UPSTREAM_PRODUCER | No native producer creates `TradePlanCandidateV31` / `CandidateHandoffV31` from admission, hypothesis and proof receipts. |
| V31_ONE_LINEAGE_E2E | No single TEST_ONLY lineage runs from canonical qualification to `transaction_a_v31`. |
| LIVE_30_PAIR_READINESS | NOT_MEASURED. |
| DIRECT_BROKER_RECEIPT_PRODUCER | `direct_broker_reconciliation_receipts` has 0 production rows (post-migration 20260919_01 check). The canonical producer has not been located yet. |

What is approved is the canonical target and runtime contract. Implementation closure happens in later PRs.

## 5. Merge prerequisites (merge stays on HOLD until all hold)

- R9 exact-S runtime verification PASS
- G1/G1b versioned per-symbol admission contract REVIEWED
- V31 implementation gap register COMPLETE
- Rollback and supersession semantics DOCUMENTED (section 6)
- Required CI ALL PASS
- Unresolved P0/P1 review threads = 0

## 6. Rollback and supersession semantics

- **Rollback** is a new record, not a revert of history. A later governance PR sets v3.1 back to `SUPERSEDED` and names the restored or new authority by exact path and hash. `dual_authority` stays `false` at every commit.
- **Supersession** of v3.1 by a later SSOT follows the same shape: a new byte-exact source copy, a new pinned hash, a new record, and a merge as the activation event.
- Artifacts produced under a previous authority keep their original `rule_version` / `selected_ssot_hash`. They are never relabelled.
- Because promotion enables nothing at runtime (section 3), neither rollback nor supersession needs any deploy or database change.
