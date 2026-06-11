# Canary Runbook — SignalWatch Lifecycle Increments C→D→E→F.1

**Date:** 2026-06-10  **Owner:** KELANA  **Scope:** Railway staged flag rollout, **no new code**.

Core principle (non-negotiable):

```text
Lebih banyak terminal explanation BOLEH.
Lebih banyak SignalJSON TIDAK BOLEH, kecuali execution contract benar-benar lengkap.
```

All four increments are flag-guarded and default OFF (F itself was already ON). Enable **one flag per
stage**, observe 15–30 min, run the per-stage acceptance, and only then proceed. If any red flag
appears, roll back that one flag (see Rollback).

## Current rollout status (2026-06-11)

```text
Repository code present       : YES (main/origin main = 62a8244c at review time)
Increment C unit behavior     : PASS (10 resolver tests)
Railway deployment confirmed  : NOT PROVEN BY THE CAPTURE
Increment C runtime validated : NO - PENDING FRESH POST-FLAG EVIDENCE
Increment D/E/F.1 rollout     : HOLD
```

The latest submitted export is not new runtime evidence. It is reported byte-for-byte identical to
the previous export (reported MD5 prefix `6160fca6`), with the same 48 GBPNZD
`[SignalWatchJSON]` events and the same event window, `2026-06-10 02:58` through `15:53 UTC`.
The two export names differ (ending `111006616` and `108027436`), but renaming or exporting the same
fixed window does not create a new canary sample.

Observed in that duplicate baseline:

```text
status / signal_family        : 48/48 MICROBOOST_WATCH
final_direction              : 48/48 WAIT
valid_for_execution=true      : 0
resolved_family               : 0/48
scenario_resolver             : 0/48
lifecycle_track               : 0/48
SignalDecisionUpdateJSON      : 0
```

Verdict: safety remains intact, but the capture proves neither that C is enabled on Railway nor that
the running deployment contains C. Do not advance to D until a later event window contains the C
fingerprint described in Stage 1.

---

## 0. Pre-rollout baseline (capture BEFORE enabling anything)

Export a fresh Railway log window from a **single deployment** (mixing deployments invalidates the
read — this is why the 9-deployment `logs.1781099239310.json` showed 0 DecisionUpdate). Save as a text
file and snapshot the KPIs below. Re-snapshot after every stage and compare.

### Capture identity and freshness gate

Run this before parsing any candidate export. A different filename is not sufficient.

```powershell
$baseline = "railway_log_baseline.txt"
$candidate = "railway_log_candidate.txt"

Get-Item $baseline,$candidate | Select-Object Name,Length,LastWriteTimeUtc
Get-FileHash $baseline,$candidate -Algorithm SHA256 | Select-Object Path,Hash

$raw = Get-Content -Raw $candidate
$timestamps = [regex]::Matches(
  $raw,
  '20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})'
) | ForEach-Object { [datetimeoffset]::Parse($_.Value) }
$timestamps | Measure-Object -Minimum -Maximum
```

Reject the candidate as **duplicate/stale** if any of these applies:

- SHA-256 equals the prior capture.
- Event maximum is not later than the prior maximum (`2026-06-10 15:53 UTC` for the current baseline).
- The export still contains the same 48-event fixed GBPNZD window.
- Events come from a deployment other than the one whose commit and flags were checked.

Before accepting a post-C sample, record all four values in the rollout evidence ledger: Railway
deployment/commit, flag value, export SHA-256, and event min/max UTC. File mtime alone is not evidence
of fresh runtime content.

| Sample | Railway deployment/commit | C flag | Content hash | Event window UTC | Verdict |
|---|---|---|---|---|---|
| Current duplicate baseline | Not established by capture | Not evidenced | Reported MD5 prefix `6160fca6` | 2026-06-10 02:58-15:53 | Baseline only |
| Required post-C capture | `152b5ff0` or newer, verify on Railway | `true` | Record SHA-256 | Maximum later than 2026-06-10 15:53 | Pending |

PowerShell KPI counter (point `$log` at the exported file):

```powershell
$log = "railway_log.txt"
function KPI($name,$pat){ "{0,-34} {1}" -f $name, (Select-String -Path $log -Pattern $pat -AllMatches).Matches.Count }
KPI "SignalThrottleIntel"            '\[SignalThrottleIntel\]'
KPI "SignalWatchJSON"                '\[SignalWatchJSON\]'
KPI "SignalDecisionUpdateJSON"       '\[SignalDecisionUpdateJSON\]'
KPI "SignalQuorumDiagnosticJSON"     '\[SignalQuorumDiagnosticJSON\]'
KPI "SignalJSON (final)"             '\[SignalJSON\]'
KPI "valid_for_execution=true"       '"valid_for_execution":true'
KPI "raw_direction_missing"          'raw_direction_missing'
KPI "MICROBOOST_WATCH generic"       '"status":"MICROBOOST_WATCH"'
KPI "EARLY_*_WATCH"                  '"status":"EARLY_(SELL|BUY)_WATCH"'
KPI "SELL/BUY_TIMING_WATCH"          '"status":"(SELL|BUY)_TIMING_WATCH"'
```

> **Two numbers that must NEVER rise across the whole rollout:**
> `valid_for_execution=true` on watch/diagnostic events (target **0**) and `[SignalJSON]` final count
> (only rises if a real, fully-validated execution-grade signal occurs — never as a side effect of a
> watch/diagnostic). If either rises unexpectedly → **emergency rollback** (see bottom).

---

## Stage 1 — Increment C (Pattern-Aware Headline Resolver)

```env
SIGNAL_WATCH_PATTERN_HEADLINE_RESOLVE_ENABLED=true
```

Observe 15–30 min. **Expected shifts:**
- `MICROBOOST_WATCH generic` ↓
- `EARLY_*_WATCH` / `*_TIMING_WATCH` ↑ (BUY@MAIN_RESISTANCE → EARLY_SELL_WATCH/SELL_TIMING_WATCH; SELL@MAIN_SUPPORT → EARLY_BUY_WATCH/BUY_TIMING_WATCH)
- `raw_direction` stays the **pressure** side; `candidate_direction` becomes the **scenario** side
- `final_direction=WAIT`, `valid_for_execution=false` everywhere

Healthy example:

```json
{"event":"signal_watch_json","signal_family":"MICROBOOST_COUNTER_ENTRY","status":"EARLY_SELL_WATCH",
 "raw_direction":"BUY","candidate_direction":"SELL","final_direction":"WAIT",
 "price_position":"MAIN_RESISTANCE","valid_for_execution":false,"is_final_signal":false}
```

**RED FLAGS → rollback C:** `valid_for_execution=true` · `final_direction=BUY/SELL` on a watch ·
`[SignalJSON]` count rises · `raw_direction` no longer the pressure side.

**GO/NO-GO:** proceed to Stage 2 only if expected shifts seen AND no red flags AND
`valid_for_execution=true`==0 AND `[SignalJSON]` flat.

For the current baseline, the fastest unambiguous C **GO** fingerprint is at least one fresh
structural-extreme watch with all of:

```text
status                 = EARLY_SELL_WATCH / SELL_TIMING_WATCH
candidate_direction    = SELL
raw_direction          = BUY
price_position         = MAIN_RESISTANCE
final_direction        = WAIT
valid_for_execution    = false
resolved_family        = MICROBOOST_COUNTER_ENTRY
```

The inverse SELL-at-MAIN_SUPPORT to BUY-watch case is equally valid. MID_RANGE counterflow remaining
generic is expected and is not a C failure. If no structural-extreme event occurs in 15-30 minutes,
extend the observation window; do not treat absence of an eligible event as either GO or NO-GO.

---

## Stage 2 — Increment D (Official Watch Finalizer Tracking)

```env
SIGNAL_WATCH_FINALIZER_TRACK_EARLY_ENABLED=true
```

Observe 15–30 min. **Expected:** `EARLY_*_WATCH` no longer hang — each cluster earns a terminal
`SignalDecisionUpdateJSON`. `SignalDecisionUpdateJSON` count ↑.

Healthy terminal statuses:

```text
FINAL_VALID_WAIT_REJECTION · FINAL_VALID_WAIT_RETEST · FINAL_VALID_WAIT_STRUCTURE_TARGET
FINAL_VALID_MANAGEMENT_ONLY · FINAL_EXPIRED · FINAL_INVALIDATED · NO_TRADE_REASONED
```

**MUST NOT happen:** watches emitted repeatedly with **no** terminal update at all ·
`[SignalJSON]` appearing *because of* an EARLY_*_WATCH · `valid_for_execution` flips true.

**GO/NO-GO:** proceed only if DecisionUpdate count rose to cover the EARLY_* watches AND
`valid_for_execution=true`==0 AND `[SignalJSON]` flat.

---

## Stage 3 — Increment E (Watch Cluster Dedup)

```env
SIGNAL_WATCH_CLUSTER_DEDUP_ENABLED=true
```

Observe 15–30 min. **Expected:** per-cluster watch spam ↓ hard. One full SignalWatchJSON per
semantic cluster/status within the TTL; DecisionUpdate still emitted.

```text
Before E:  GBPCHF = 28 repeated watch
After  E:  GBPCHF = 1 full watch per semantic cluster/status  + 1 terminal DecisionUpdate
```

**MUST NOT happen:** the **first** watch of a cluster disappears · DecisionUpdate disappears ·
`[SignalJSON]` gets suppressed · a real **status change** (`EARLY_SELL_WATCH → SELL_TIMING_WATCH`)
gets swallowed (status/direction/price_position/valid_for_execution changes MUST still emit — dedup is
for semantic duplicates only).

**GO/NO-GO:** proceed only if duplicates dropped AND status transitions still emit AND DecisionUpdate
unaffected.

---

## Stage 4 — Increment F.1 (Contextless Quorum Diagnostic) + confirm F

```env
SIGNAL_THROTTLE_ALLOWED_QUORUM_CONTEXTLESS_DIAGNOSTIC_ENABLED=true
SIGNAL_THROTTLE_ALLOWED_QUORUM_DECISION_UPDATE_ENABLED=true   # F (already default ON; set explicit to remove ambiguity)
```

Observe 15–30 min. **Expected (only when market context / reference price is missing):**

```json
{"event":"signal_quorum_terminal_diagnostic_json","terminal_status":"NO_TRADE_REASONED_CONTEXTLESS",
 "signal_family":"SIGNAL_THROTTLE_ALLOWED_QUORUM","final_direction":"WAIT",
 "valid_for_execution":false,"is_final_signal":false,
 "watch_promotion_blockers":["WATCH_PROMOTION_FAILED","MARKET_CONTEXT_MISSING","REFERENCE_PRICE_MISSING"]}
```

Prefix is `[SignalQuorumDiagnosticJSON]` — **diagnostic only**, NOT a signal lifecycle decision.

**MUST NOT happen:** `[SignalDecisionUpdateJSON]` without a price · `[SignalJSON]` without a price ·
fabricated `entry_zone` / `signal_valid_price` · `valid_for_execution=true`.

**GO/NO-GO (final):** quorum that fails promotion now ALWAYS has *some* terminal (priced
NO_TRADE_REASONED when context exists, contextless diagnostic when it doesn't), AND no priceless
`[SignalDecisionUpdateJSON]`/`[SignalJSON]`, AND `valid_for_execution=true`==0.

---

## Target end-state (all flags ON)

```text
raw_direction_missing        : turun / tetap rendah
MICROBOOST_WATCH generic     : turun
EARLY_*_WATCH                : naik wajar
SignalDecisionUpdateJSON     : naik
duplicate watch per cluster  : turun
SignalJSON (final)           : tetap 0 kecuali benar-benar execution-grade
valid_for_execution=true     : tetap 0 pada watch/diagnostic
```

## Rollback order (peel from the last flag first)

```text
1. Disable SIGNAL_THROTTLE_ALLOWED_QUORUM_CONTEXTLESS_DIAGNOSTIC_ENABLED   (F.1)
2. Disable SIGNAL_WATCH_CLUSTER_DEDUP_ENABLED                              (E)
3. Disable SIGNAL_WATCH_FINALIZER_TRACK_EARLY_ENABLED                      (D)
4. Disable SIGNAL_WATCH_PATTERN_HEADLINE_RESOLVE_ENABLED                   (C)
```

Do NOT disable everything at once **unless** there is a fake SignalJSON or an execution leak.

## EMERGENCY rollback (disable all four immediately) if ANY of:

```text
- [SignalJSON] count rises without a complete tradeplan
- valid_for_execution=true on any watch or diagnostic
- final_direction = BUY/SELL emitted from an EARLY_*_WATCH
- fabricated price / entry_zone on a watch or diagnostic
```

---

### Quick spot-checks (PowerShell, against the exported log)

```powershell
# Any execution leak on watch/diagnostic? (expect: no output)
Select-String -Path $log -Pattern '"valid_for_execution":true' | Select-String -Pattern 'WATCH|DIAGNOSTIC'
# EARLY_* watches that leaned the scenario side correctly:
Select-String -Path $log -Pattern '"status":"EARLY_SELL_WATCH".*"candidate_direction":"SELL"'
# Contextless diagnostics actually carry the missing-context blockers:
Select-String -Path $log -Pattern '\[SignalQuorumDiagnosticJSON\].*MARKET_CONTEXT_MISSING'
```

> Note: the standalone funnel auditor `promotion_audit.py` (kept in `~/Downloads`, intentionally outside
> the repo) can be run on a single-deployment CSV export for the full S0–S7 funnel + duplicate-cluster
> report if a stage's KPI shift is ambiguous.
