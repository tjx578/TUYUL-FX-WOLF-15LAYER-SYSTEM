# Canary Runbook — Increment H1 (HTF Structure Snapshot)

**Date:** 2026-06-11  **Owner:** KELANA  **Scope:** Railway single-flag enable, **no new code**.

Core principle (non-negotiable):

```text
H1 hanya observability struktur Daily/H4.
Lebih banyak snapshot context BOLEH.
SignalJSON / valid_for_execution=true TIDAK BOLEH bertambah sama sekali.
```

This canary proves the HTF Structure Snapshot **emits at runtime, does not crash, and does not change
the safety counter** — before we touch anything closer to Microboost/H4 intelligence (`raw_direction`
propagation is the *next* step, intentionally NOT in this canary).

## Disciplined order (locked)

```text
1. Canary H1 snapshot              <-- THIS RUNBOOK
2. Validate runtime, single-deployment capture
3. THEN fix raw_direction propagation
4. THEN H4 HTF Microboost Interpreter
```

## What ships (already on origin/main)

```text
analysis/htf_structure_snapshot.py            : pure resolver (non-executable), 28 unit tests
pipeline/wolf_constitutional_pipeline.py      : _emit_htf_structure_snapshot(symbol) in the
                                                _emit_microboost_watch_shadow observability lane
tests/test_htf_snapshot_pipeline_wiring.py    : 4 wiring tests (flag OFF/ON, dedup, failure-swallow)
```

Hard invariant in code: `valid_for_execution` is always `False`, `is_final_signal` always `False`,
emit is wrapped in try/except, flag is checked **before** any candle read (zero overhead when OFF).

---

## Stage 1 — Enable H1 only

Set exactly one flag. Leave everything else as-is. **Do NOT enable H2/H4/anything else.**

```env
HTF_STRUCTURE_SNAPSHOT_ENABLED=true
```

Explicitly keep OFF (must remain default this stage):

```env
HTF_DAILY_PHASE_FEED_ENABLED=false      # Step 1 Daily feed — separate canary, not now
# no H2 / H4 / limit-watch flags exist-or-enabled
```

Deploy once. Then **freeze deployment churn** (root cause that stalled the prior SignalWatch canary —
see [CANARY_RUNBOOK_SIGNALWATCH_LIFECYCLE_2026-06-10.md](CANARY_RUNBOOK_SIGNALWATCH_LIFECYCLE_2026-06-10.md)):
do not redeploy/restart during the observation window, or the flag never reaches steady state and the
capture is a boot-snapshot burst, not a canary.

Observe **one** stable deployment for 15–30 min over a session with active pairs (London/NY overlap
gives the most GBPNZD/cross pressure).

---

## Capture (single deployment_id)

Filter the log export by the running `deployment_id` and these tokens:

```text
<deployment_id> HTFStructureSnapshot
<deployment_id> htf_structure_snapshot_json
<deployment_id> SignalWatchJSON
<deployment_id> SignalDecisionUpdateJSON
<deployment_id> SignalJSON
<deployment_id> valid_for_execution
```

A valid capture is a **single** `deployment_id`, a contiguous event window > 15 min, and at least one
`[HTFStructureSnapshot]` line. A renamed/re-exported identical window is NOT a new sample.

---

## Acceptance criteria

```text
[HTFStructureSnapshot] appears                 = PASS (>=1 line)
event == htf_structure_snapshot_json           = PASS
valid_for_execution=true   (any source)        = 0      <-- hard gate
is_final_signal=true                            = 0      <-- hard gate
SignalJSON                                      = 0 new  <-- hard gate
pipeline crash / traceback                      = 0
snapshot dedup (no per-tick spam)               = PASS (per-symbol structure repeats suppressed)
Daily/H4 fields plausible                       = manual review (see below)
```

Any hard-gate violation → roll back immediately (Rollback below). H1 must never open an execution path.

### Manual review — "fields masuk akal"

For each distinct symbol, sanity-check one snapshot against the chart:

```text
daily_bias        in {BULLISH, BEARISH, RANGE, TRANSITION, NO_BIAS} and matches the Daily trend
h4_structure      in {BULLISH_IMPULSE, BULLISH_PULLBACK, BEARISH_IMPULSE, BEARISH_PULLBACK, RANGE, NO_STRUCTURE}
price_location    in {PREMIUM, DISCOUNT, EQUILIBRIUM, H4_SUPPLY, H4_DEMAND, UNKNOWN}
blocked_playbook  contains BUY_LIMIT whenever daily_bias is BEARISH / TRANSITION / NO_BIAS
                  contains SELL_LIMIT whenever daily_bias is BULLISH (mirror)
```

First line we want to see (shape, GBPNZD example):

```json
{
  "event": "htf_structure_snapshot_json",
  "symbol": "GBPNZD",
  "daily_bias": "BEARISH",
  "h4_structure": "BEARISH_PULLBACK",
  "price_location": "PREMIUM",
  "allowed_playbook": "SELL_ON_REJECTION",
  "blocked_playbook": ["BUY_LIMIT", "BUY_BREAKOUT_CHASE"],
  "valid_for_execution": false,
  "is_final_signal": false
}
```

`data_sufficient=false` is acceptable during warmup (insufficient Daily/H4 bars) — it must degrade to
`daily_bias=NO_BIAS` + full `blocked_playbook`, never to an execution path.

---

## Rollback

```env
HTF_STRUCTURE_SNAPSHOT_ENABLED=false
```

Single-flag, instant. Removes only the snapshot log line; no other behavior depends on it. No code
revert required.

---

## Exit → next step

```text
H1 canary PASS (single-deployment capture with [HTFStructureSnapshot], all hard gates 0)
  -> LOCK H1
  -> proceed to raw_direction propagation fix
       SignalThrottleIntel.raw_direction
         -> pressure block dominant_direction
         -> Microboost block raw_direction
         -> SignalWatchJSON directional interpretation
```

Do not advance to the `raw_direction` fix until a single-deployment capture contains the
`[HTFStructureSnapshot]` fingerprint above with every hard gate at 0.

## Roadmap status

```text
H1 resolver pure        = DONE (28 tests)
H1 pipeline wiring      = DONE (4 tests)
Step 1 Daily Phase Feed = DONE in code, flag OFF (9 tests) — its own canary, separate from H1
H1 canary runtime       = THIS RUNBOOK (pending single-deployment capture)
After H1 PASS           = raw_direction propagation fix
Then                    = Increment L / H4 default-deny limit-watch
```
