# Canary Runbook — Step 1 (HTF Daily Phase Feed)

**Date:** 2026-06-11  **Owner:** KELANA  **Scope:** Railway single-flag enable, **no new code**.

Prereq: **H1 canary PASS / LOCKED** (see
[CANARY_RUNBOOK_HTF_STRUCTURE_SNAPSHOT_H1_2026-06-11.md](CANARY_RUNBOOK_HTF_STRUCTURE_SNAPSHOT_H1_2026-06-11.md)).
Keep `HTF_STRUCTURE_SNAPSHOT_ENABLED=true` — the H1 snapshot's `daily_bias` is the single Daily
source of truth for this feed.

Core principle (non-negotiable):

```text
Daily context BOLEH menghidupkan rule no-chase / filter / management yang sudah tertulis.
Daily TIDAK BOLEH menjadi hard execution blocker.
valid_for_execution=true TIDAK BOLEH bertambah. SignalJSON baru TIDAK BOLEH.
```

## What this flag actually does (read before enabling)

Unlike H1 (a pure log line), this flag **changes matcher input**: it populates
`MarketContext.d1_phase`, which the golden matcher already reads at
[matcher.py:325](signalthrottle_patterns/matcher.py) and :555 but which was previously always empty
(dead code). Turning it ON can therefore shift `selected_pattern_id`, `pattern_family`,
`pattern_evidence`, and the pattern scores. **That shift is the point** — we are waking written-but-dead
Daily rules. It must shift toward *more conservative* reads (no-chase / filter / management), never
toward new entries.

```text
Source of truth : H1 snapshot daily_bias (BULLISH/BEARISH/RANGE/TRANSITION/NO_BIAS)
Fallback        : _derive_timeframe_phase(symbol,"D1") when snapshot has no read yet
Consumer        : matcher Daily rules (daily_conflict, MACRO_BULLISH_INTRADAY_PULLBACK,
                  HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE, late_upper_density_no_chase, ...)
Not changed     : resolver pattern, candidate_direction, microboost thresholds, SignalJSON, exec gate
```

Code: `MarketContext.d1_phase` ([market_context_validator.py:68](market_context_validator.py)),
`_derive_daily_phase_feed` (pipeline), `tests/test_htf_daily_phase_feed.py` (9 tests, incl. a matcher
rule that flips ON only when `d1_phase` is present).

---

## Stage 0 — Baseline capture (flag OFF)

Before enabling, capture one single-deployment window with the flag still OFF and record the matcher
output distribution. This is the comparison anchor (Daily rules are dead-code here).

```env
HTF_DAILY_PHASE_FEED_ENABLED=false   # baseline
```

Record from `[SignalWatchJSON]` rows:

```text
count valid_for_execution=true        (expect 0)
count SignalJSON                       (expect 0)
distribution of pattern_family
set of pattern_evidence tokens present
```

---

## Stage 1 — Enable Daily Phase Feed

```env
HTF_STRUCTURE_SNAPSHOT_ENABLED=true   # keep ON (Daily source of truth)
HTF_DAILY_PHASE_FEED_ENABLED=true     # <-- the only change
```

Deploy once, **freeze deployment churn**, observe one stable deployment 15–30 min over an active
session (London/NY overlap).

---

## Capture (single deployment_id)

```text
<deployment_id> HTFStructureSnapshot
<deployment_id> htf_structure_snapshot_json
<deployment_id> SignalWatchJSON
<deployment_id> pattern_family
<deployment_id> pattern_evidence
<deployment_id> SignalDecisionUpdateJSON
<deployment_id> SignalJSON
<deployment_id> valid_for_execution
```

---

## Acceptance criteria

Hard gates (vs the Stage-0 baseline, same-deployment):

```text
valid_for_execution=true   : must NOT increase vs baseline (target 0)   <-- hard gate
is_final_signal=true       : 0                                          <-- hard gate
SignalJSON                 : 0 new                                      <-- hard gate
pipeline crash / traceback : 0
```

Activation evidence (proves the dead code woke up — at least one, absent at baseline, now present):

```text
pattern_evidence contains any Daily-dependent token, e.g.:
  high_density_bearish_context_no_chase
  late_upper_density_no_chase
  macro_bullish_intraday_pullback_wait_reclaim_or_support_hold
  repeated_pressure_m15_d1_conflict
  mtf_bullish_higher_tf_lower_tf_pullback_decision
```

Sanity (direction of the shift):

```text
Net effect is MORE filtering / no-chase / management, NOT more entries.
Cross-check: for a symbol, the Daily-aware read must agree with that symbol's
[HTFStructureSnapshot] daily_bias (e.g. daily_bias=BEARISH should not produce a
bullish-continuation Daily evidence token).
```

If any hard gate trips, or the shift adds entries / promotes execution → roll back immediately.

---

## Rollback

```env
HTF_DAILY_PHASE_FEED_ENABLED=false
```

Single-flag, instant. `d1_phase` returns to absent and the matcher reverts to legacy (Daily rules
dormant again). No code revert required.

---

## Exit → next step

```text
Step 1 PASS (Daily evidence tokens present, all hard gates 0, shift is conservative)
  -> LOCK Step 1
  -> proceed to raw_direction propagation fix
       SignalThrottleIntel.raw_direction -> pressure block dominant_direction
         -> Microboost block raw_direction -> SignalWatchJSON directional interpretation
     (runtime already proves the gap: H1 capture had raw_direction=null on all 25 microboost rows)
```

## Roadmap status

```text
H1 canary                = PASS / LOCKED 2026-06-11
Step 1 Daily Phase Feed  = code DONE flag OFF (9 tests) ; THIS RUNBOOK = pending runtime
After Step 1 PASS        = raw_direction propagation fix
Then                     = Step 2 feed H1 price_location/liquidity to matcher
Then                     = Increment L / H4 default-deny limit-watch -> H5 structural SL/TP
```
