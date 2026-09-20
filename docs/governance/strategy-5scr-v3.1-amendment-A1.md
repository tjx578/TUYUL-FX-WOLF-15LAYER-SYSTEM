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

## 3. Normative sections — PressureRange (12A)

Added 2026-09-21 after the 12A audit. 12A acceptance was **NOT MET**: `pressure_range_id` derivation, the
`low`/`high` derivation formula, window closure, coverage semantics and the refresh-versus-material rule are all
`NOT_DEFINED_BY_AUTHORITY` in v3.1. The owner classified the behavioral gaps (G3–G6) as amendment-first. These
four sections are that amendment. They are registered as entries A1-09 … A1-12 so the machine record covers them.

The whole base authority for `PressureRange` is seven clauses: §16.1, §16.2, §8.5, §4.1, §5/§28, plus Audit/Replay
v3 line 55 and §11 steps 3 and 5. Everything these sections define is genuinely absent from that surface.

### A1-09 · GAP_FILL · A1.1 PressureRange material observation window

- **Source:** 12A audit (G5).
- **Base clauses:** §16.1, §16.2, §8.5, §8.3, §11.5.
- **Base behavior:** §8.5 defines where the window **starts** per admission class. §16.2 declares
  `ended_at: timestamp|null`. Nothing in any source defines what closes the window, whether a closed window may
  reopen, or what happens to evidence that arrives late.
- **Amended behavior:**
  - **Start (restated from §8.5, unchanged):** `CANONICAL_RAW` anchors at `block_started_at`; `MATURE_ADVISORY`
    anchors at its first retained material advisory event and **must** record its exact coverage start and gaps.
    Fabricating coverage before evidence exists stays forbidden.
  - The record carries `coverage_anchor_rule` ∈ {`RAW_BLOCK_START`, `FIRST_RETAINED_ADVISORY_EVENT`}. It is a
    **derivation label**: never an admission class, never an authority, never a containment flag.
  - **As-of bound:** the record carries `observed_through_utc`. No observation whose close time is after it may
    contribute (§11.5 `FUTURE_LEAKAGE_BLOCK`). This makes the range replay-deterministic.
  - **Closure authority (NORMATIVE, owner decision 2026-09-21):** the **MarketEpisode close is the sole
    closure authority**. `ended_at` is that episode close. Derivation basis: §16.1 scopes the range to the
    *pressure episode*.
  - **Lifecycle supersession does NOT close the window** (owner decision 2026-09-21). A superseded lifecycle
    stops progressing; the material price evidence of its episode keeps its own window.
  - **Raw-block termination alone does NOT close the window** (owner decision 2026-09-21). The block bounds
    where a canonical window *starts* (§8.5); it does not bound where it ends.
  - **Reopening a closed canonical range: false** (owner decision 2026-09-21). A closed window is never reopened
    and never revived, mirroring the no-resurrection discipline already recorded for context epochs (A1-03) and
    theses (A1-08).
  - **Late evidence:** while the window is open it is appended. After closure it is **rejected** and recorded as a
    permanent gap; it never mutates a closed range.
- **Reason:** `ended_at` determines the evidence window, and therefore `source_price_ids`, the `low`/`high`
  universe, coverage and `evidence_hash`. It cannot be an implementation detail. A single closure
  authority also keeps one episode from producing two differently-bounded ranges.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A1-10 · GAP_FILL · A1.2 Material range derivation

- **Source:** 12A audit (G4).
- **Base clauses:** §16.2, §11.5, §11.2.
- **Base behavior:** Audit/Replay v3 §11 step 5 says "hitung material pressure range **tanpa future price**".
  That constrains *when* an observation may count, never *how* `low` and `high` are derived, and never *which*
  prices qualify. No formula exists in any source.
- **Amended behavior — the qualifying observation universe is defined first:**

  A `QualifyingPressurePriceObservation` is an observation that satisfies **all** of:
  1. **Eligible source:** an authoritative closed M1 candle of the range's canonical symbol. Audit/Replay v3
     line 55 binds `M1/tick` to the pressure range. Tick-level observations become eligible **only** when a tick
     store is declared authoritative by a versioned policy; until then the universe is M1 only.
  2. **Closed only:** `is_closed = true`. A `FORMING` period never qualifies (§11.5).
  3. **Quality:** the candle is not `UNKNOWN`, not `INCOMPLETE` and not `QUARANTINED` (§11.5).
  4. **No future price:** `close_time <= observed_through_utc`, otherwise `FUTURE_LEAKAGE_BLOCK`.
  5. **Inside the window:** `started_at <= open_time`, and `close_time <= ended_at` once the window is closed.
  6. **Deduplicated:** unique by candle evidence id. Two distinct evidence ids for the same period are a
     data-quality incident: that period becomes a **gap**, never a silent pick.
  7. **Period-aligned (NORMATIVE, owner decision 2026-09-21 — G2/G6 cardinality consistency):** every entry of
     `source_price_ids` resolves to **exactly one** expected canonical period, and
     `len(source_price_ids) == len(qualified set)`. Because A1.3 evaluates coverage **per canonical period**,
     a flat list of arbitrary raw tick ids would make coverage uncomputable from the record alone. Tick-level
     evidence never appears as a free list: it may contribute only through the canonical period it aggregates
     into, and that aggregation is itself authoritative evidence carrying its own id.

  Only then:
  - `low = min(observation.low)` and `high = max(observation.high)` over the qualifying set — **wicks, not
    bodies**, because §16.2 names it the material *observed price range*.
  - Zero qualifying observations → `low = high = null` and `price_coverage_status = MISSING`. A range is never
    reported as `0`, and never as a degenerate point standing in for absent evidence.
  - A `QUARANTINED` candle is excluded from `low`/`high` **and** forces the coverage status of A1.3. The outlier
    rule that produces `QUARANTINED` remains §11.5's; this section introduces none.
  - Every policy input (provider calendar, outlier rule version) comes from a **versioned hashed policy**.
    No default may be compiled in.
- **Reason:** without the qualifying universe, `min`/`max` is ambiguous and the geometry that depends on it is
  not reproducible across replays.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A1-11 · GAP_FILL · A1.3 Price coverage semantics

- **Source:** 12A audit (G6).
- **Base clauses:** §16.2, §8.5, §11.5.
- **Base behavior:** §16.2 fixes four values (`COMPLETE|PARTIAL|MISSING|QUARANTINED`) and §8.5 fixes the
  consequence of incomplete coverage. Nothing defines what selects a value.
- **Amended behavior — deliberately threshold-free:**

  ```text
  expected set  = the authoritative M1 periods the provider calendar declares for the window (§11.5)
  qualified set = the qualifying observations of A1.2
  ```

  ```text
  QUARANTINED = at least one expected period whose evidence is an unresolved gap/outlier (§11.5)
  MISSING     = the qualified set is empty
  PARTIAL     = at least one qualifying observation AND at least one expected period unmatched
  COMPLETE    = the expected set is non-empty AND every expected period has exactly one qualifying
                observation AND there is no unresolved gap or outlier
  ```

  Precedence, highest first: `QUARANTINED` > `MISSING` > `PARTIAL` > `COMPLETE`.

  Coverage is computed **per canonical period**, so it is well defined only against the period-aligned
  evidence cardinality of A1.2 clause 7. A record whose `source_price_ids` cannot be resolved one-to-one
  to expected periods has an **undecidable** coverage status and is rejected, never defaulted.

  - **No percentage threshold is introduced.** Coverage is decided by set completeness against the provider
    calendar, not by an invented ratio.
  - **Actionability (restated from §8.5, unchanged):** only `COMPLETE` permits `structural_authority = true`.
    The other three place the lifecycle in `WAITING_PRICE_COVERAGE` with `structural_authority = false`.
    The range itself never holds authority in any state.
  - **The vocabulary is closed.** `DEGRADED` and `UNAVAILABLE` must not be introduced. `STALE` belongs to
    `observed_price_status` and the §11.3 quote-feed FSM and must not be promoted into `price_coverage_status` —
    they are different axes.
  - `missing evidence ≠ empty range ≠ zero range ≠ valid complete range`.
- **Reason:** coverage decides actionability. An arbitrary ratio would silently move the boundary between
  analysable and non-analysable lineages.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A1-12 · GAP_FILL · A1.4 Change classification and downstream re-evaluation

- **Source:** 12A audit (G3).
- **Base clauses:** §15.1, §15.2, §16.2.
- **Base behavior:** §15.1 lists "ExecutionBox material revision" as a material trigger and §15.2 forbids
  duplicate telemetry from creating "box version baru". **`PressureRange` is named in neither.** The range has no
  refresh-versus-material rule of its own anywhere in the sources.
- **Amended behavior — three change classes over a normative field partition:**

  ```text
  GEOMETRY_MATERIAL : started_at, ended_at, coverage_anchor_rule, low, high
  COVERAGE          : price_coverage_status, coverage_gaps
  EVIDENCE          : source_price_ids, observed_through_utc
  NON_MATERIAL      : telemetry count, deployment/replica/cluster, request id, publisher,
                      reference price, evidence ordering provenance
  ```

  Classification, highest precedence first:

  ```text
  MATERIAL_RANGE_CHANGE = any GEOMETRY_MATERIAL field differs
  COVERAGE_CHANGE       = no GEOMETRY_MATERIAL difference AND any COVERAGE field differs
  EVIDENCE_REFRESH      = only EVIDENCE fields differ
  (no class)            = only NON_MATERIAL fields differ -> nothing is recorded (§15.2)
  ```

  Downstream re-evaluation:

  | Change | PressureRange | Lifecycle | StructuralTarget | ExecutionBox |
  |---|---|---|---|---|
  | `EVIDENCE_REFRESH` | evidence appended | no structural change | no | no |
  | `COVERAGE_CHANGE` | geometry unchanged | re-evaluate authority / actionability | conditional (12B) | `NOT_DEFINED` — deferred to G7/12C |
  | `MATERIAL_RANGE_CHANGE` | material change | re-evaluate | **yes** | **yes, once 12C exists** |
  | non-material only | none | none | no | no |

  - A new authoritative M1 close is a §15.1 trigger for the **scheduler**. Whether it yields a class above is
    decided by this partition, not by the trigger: a close that lands inside the existing `[low, high]` and
    changes no coverage is an `EVIDENCE_REFRESH`.
  - **Coverage may change while `low` and `high` are identical.** That case is `COVERAGE_CHANGE`, not
    `EVIDENCE_REFRESH`, and it re-evaluates lifecycle actionability. This is the case a two-class model misses.
  - `COVERAGE_CHANGE` does **not** by itself imply an ExecutionBox revision. That question is G7 and belongs to
    12C.
- **Reason:** without this partition every authoritative close would cascade
  `range → target → box supersede → lifecycle churn`, and the chain would never be stable.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

## 4. Non-normative annex (12A)

These are recorded for traceability. They are **not** amendments and grant nothing.

- **G1 · `pressure_range_id` derivation — implementation GAP_FILL (Route 2).** §16.2 declares the uuid; only the
  encoding is missing. The derivation must be deterministic, immutable, collision-safe, versioned, and must never
  read telemetry, deployment, request or reference-price fields. Because §8.5 gives the two admission classes
  materially different windows, an advisory range and a canonical range on the same episode are **different
  objects**: the id is **not** preserved across an authority upgrade, and the advisory range is never mutated.
  This is the one place in the V31 lineage where identity legitimately moves on upgrade.
- **G2 · `source_price_ids` representation — implementation GAP_FILL (Route 2).** The canonical contract keeps
  them as **opaque source price evidence references** to the authoritative price evidence that formed the range.
  Implementations may namespace them (`candle:<id>`). No new market semantics is attached, and the element type
  is not narrowed further until authority narrows it.
  **The cardinality is no longer an annex matter:** A1.2 clause 7 makes period alignment normative, so a
  reference must resolve to exactly one canonical period. `tick:<id>` is therefore not a legal top-level
  element; tick evidence enters only through the canonical period that aggregates it.
- **G7 · ExecutionBox consumption — DEFERRED to 12C.** No source states what the box takes from the range.
  `PressureRange` is producer-only. 12C may not begin implementation until G7 is resolved.
- **G8 · `material_pressure_range_hash` — INTENTIONALLY NOT CREATED.** Authority declares only `evidence_hash`.
  Material change is detected from the explicit field partition of A1-12, not from a new canonical hash. If a
  deterministic material hash is later required as an inter-service contract, it enters through its own
  amendment entry.

## 5. Not amendments (recorded to prevent drift)

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

## 6. Approval

This record is a DRAFT. Approval needs the owner's explicit decision per entry, together with the shadow, replay and OOS evidence each entry requires. The authority-promotion record must then reference `base_ssot_hash` together with `active_amendments = [A1 sha256]`. Promoting bare v3.1 alone is not permitted.
