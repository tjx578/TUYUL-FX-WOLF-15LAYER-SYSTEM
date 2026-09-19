# Strategy 5S-CR SSOT v3.1: Amendment A1 (DRAFT)

```yaml
amendment_id: WOLF15-5SCR-SSOT-V3.1-A1
status: DRAFT_NOT_APPROVED
base_ssot:
  document_id: WOLF15-5SCR-SSOT-V3.1-CANDIDATE
  path: docs/remediation/2026-09-09/source-binding/selected-ssot-v3.1.md
  sha256: 6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902
  document_bytes_modified: false
effective_authority_model: BASE_SSOT_PLUS_EXPLICIT_AMENDMENTS
dual_authority: false
runtime_activation: EXPLICIT_ONLY
final_approver: OWNER
```

## 1. Purpose and rule

Strategy authority lineage: **SSOT v2 → Audit/Replay Workflow v3 → SSOT v3.1**. Behavior that goes beyond v3.1 is never folded silently into "v3.1". It must be recorded here as an explicit amendment entry.

```text
EFFECTIVE STRATEGY AUTHORITY = SSOT v3.1 (6daea387…) + this amendment (sha256 pinned in the JSON record)
```

- A1 overrides or fills **only** the clauses its entries name. Every other v3.1 clause stays in force unchanged.
- The v3.1 file is never edited.
- A1 grants no runtime activation. Every entry becomes effective at runtime only through its own explicit owner activation, after the evidence the entry requires (§24/§25 discipline).

Entry types:
- `CONFLICT_OVERRIDE`: the entry contradicts and replaces a v3.1 clause.
- `GAP_FILL`: v3.1 is silent (NOT_DEFINED_BY_AUTHORITY), and the entry defines the behavior.

## 2. Entries

### A1-01 · CONFLICT_OVERRIDE · Per-symbol isolated PairAdmission

- **Source:** PR #492 (`5scr.pair-admission.per-symbol-isolated.v3`).
- **Base clauses:**
  - §5 raw path "global active block FSM";
  - §7.2 Global block FSM;
  - §7.3 eligibility (`cross_symbol_interruption_count = 0`);
  - §7.7 trigger "block difinalisasi oleh symbol lain";
  - §7.11 `PairAdmissionEvaluationV3_1` block shape;
  - §24.3 shadow gate "PairAdmission raw-only tetap identik";
  - §27 "global ActiveBlock".
- **Base behavior:** one global raw block. A different symbol finalizes the active block. Eligibility requires ≥ 300 s with zero cross-symbol interruption. The shadow gate requires PairAdmission outcomes to stay identical to the old path.
- **Amended behavior:**
  - Each canonical symbol of an explicit universe has its own raw admission lineage. Events of other symbols neither interrupt nor finalize it.
  - Eligibility keeps the raw-only authority (§7.1) and the policy-versioned threshold, measured per symbol.
  - A global safety state is an **overlay**: it gates progression and never rewrites a per-symbol lineage.
  - Legacy `raw-ledger.v2` evaluations stay replayable unchanged.
  - The §24.3 gate becomes: old-path vs A1-path PairAdmission outcomes **may differ by design**. Every divergence is recorded per symbol with both lineages, and derived pressure still never becomes PairAdmission authority.
- **Unchanged:** §7.1 raw-only authority, §7.4 evaluation states, §7.5 completeness invariant, §7.10 independence from data quality.
- **Reason:** automatic per-pair canonical qualification across 30 pairs. Under the global FSM, activity on one symbol finalizes the admission of every other symbol.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A1-02 · GAP_FILL · Opposite pressure supersedes the active hypothesis

- **Source:** PR #494.
- **Base clauses:** §4.2 "opposite direction → hypothesis/thesis baru"; §10; §28.13.
- **Base behavior:** a new hypothesis is required for the opposite direction. The fate of the old active hypothesis is not defined.
- **Amended behavior:** one active hypothesis per lifecycle. A pressure-level flip marks the old hypothesis `INVALIDATED` with reason `OPPOSITE_DIRECTION_SUPERSEDED` (append-only, hash-chained) and moves the single active pointer by compare-and-set. Old history is never rewritten.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A1-03 · GAP_FILL · Expired context epoch with unchanged material stays closed

- **Source:** PR #495.
- **Base clauses:** §12.1; §18 `CONTEXT_EPOCH_VALID_UNTIL`.
- **Base behavior:** the epoch expires. Re-opening with identical material is not defined.
- **Amended behavior:** no new epoch and no revival (`EPOCH_EXPIRED_MATERIAL_UNCHANGED`, fail closed). Only a material context change opens a new epoch.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A1-04 · GAP_FILL · Deferred context never promotes structural proof

- **Source:** PR #497.
- **Base clauses:** §12.4 DEFER; §14.3.
- **Base behavior:** DEFER is a legal context outcome. Whether structural proof may be promoted under DEFER is not defined.
- **Amended behavior:** under DEFER, structural proof is not promoted (`CONTEXT_DEFERRED_NO_PROOF_PROMOTION`).
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A1-05 · GAP_FILL · Thesis lifecycle entry and binding

- **Source:** PR #498.
- **Base clauses:** §14.1 (thesis only if proof is available) vs §14.2/§28.16 (`PENDING_H1`, `PENDING_M15`). These are in tension inside v3.1.
- **Amended behavior:**
  - Evidence may exist before the thesis.
  - A thesis is born `PENDING_H1` on ALIGN with an active same-direction hypothesis.
  - Binding a complete atomic H1+M15 proof moves it to `STRUCTURALLY_CONFIRMED`.
  - `PENDING_M15` is reserved.
  - `PENDING_CONTEXT` and `DORMANT` are unreachable (a non-null `context_epoch_id` is required).
  - Direction authority is derived: true only in `STRUCTURALLY_CONFIRMED` and `GEOMETRY_PENDING`. It is never execution authority.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A1-06 · GAP_FILL · Thesis clock

- **Source:** PR #498.
- **Base clauses:** §18 (no thesis clock in the list); §7.9 "thesis expiry"; §28.16 `EXPIRED`.
- **Amended behavior:**
  - A hashed, versioned thesis clock policy with no default TTL.
  - `valid_until = min(valid_from + ttl, context_epoch.valid_until)`, with an explicit `valid_until_bound`.
  - The deadline is immutable, and expiry is terminal.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A1-07 · GAP_FILL · Proof actionability at thesis binding

- **Source:** PR #498.
- **Base clauses:** §14.3; §14.5.
- **Base behavior:** ordering is defined. Whether later closed candles may invalidate the proof before binding is not defined.
- **Amended behavior:** a structural proof is immutable evidence. Binding requires a hashed actionability policy with:
  - contiguous closed H1/M15 coverage from the proof to the decision time;
  - no later adjacent counter-H1 break;
  - no later M15 close back through the break level.

  Missing coverage fails closed. The predicates derive from the V1 thesis liveness rules.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A1-08 · GAP_FILL · Thesis termination triggers and cardinality

- **Source:** PR #498.
- **Base clauses:** §4.2 (context epoch → 0..N theses); §21.5 `THESIS_INVALIDATED` / `THESIS_SUPERSEDED`; §28.16.
- **Amended behavior:**
  - context epoch superseded → thesis `SUPERSEDED`;
  - context epoch expired → thesis `EXPIRED`;
  - canonical structural invalidation of a confirmed thesis → `INVALIDATED`;
  - at most one active thesis per lifecycle (compare-and-set), so a new thesis requires the previous one to be terminal;
  - terminal theses are never revived.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

## 3. Not amendments (recorded to prevent drift)

- **Conservative subsets that implement less than v3.1 are `PARTIAL`, not amendments:**
  - CANONICAL_RAW-only hypothesis;
  - counter-pressure proof and thesis;
  - non-CONTINUATION thesis classes;
  - additional proofs after confirmation (§19.4 child trigger).
- **Implementation details:** UUIDv5 identities, canonical JSON hashing, and the native ordered-proof projection and verifier (#499).
- **Conformance gaps to be closed by implementation, not by amendment:**
  - StrategyAnalysisAdmission (§7A.4) as its own object;
  - lifecycle identity from the market episode (§4.2, §7A.6);
  - PairAdmissionCoverage (§7.12).

## 4. Approval

This record is a DRAFT. Approval needs the owner's explicit decision per entry, together with the shadow, replay and OOS evidence each entry requires. The authority-promotion record must then reference `base_ssot_hash` together with `active_amendments = [A1 sha256]`. Promoting bare v3.1 alone is not permitted.
