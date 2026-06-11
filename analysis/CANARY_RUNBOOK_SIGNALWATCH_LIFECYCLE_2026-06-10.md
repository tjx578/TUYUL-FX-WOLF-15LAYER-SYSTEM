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
Repository code present       : YES (origin/main = 79a05a32; C/D/E/F.1 shipped up to 152b5ff0)
Increment C unit behavior     : PASS (10 resolver tests + 4 golden-reference)
Railway deployment confirmed  : NOT PROVEN - attempts #1-#2 idle on eligible input; #2 mixes 13 deployments
Increment C runtime validated : NO - #2 (sha256 a9e5a6bc) fresh but mixes 13 deploys; live deploy unproven (0 eligible on newest)
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

## Stage-1 attempt #1 ledger — C Pattern Headline Resolver

First capture that PASSES the freshness gate (`logs.1781142295337.json`): sha256 `65cc2e5e…`,
event window `2026-06-10 08:35 → 2026-06-11 01:44 UTC`, 168 `[SignalWatchJSON]` across 10 symbols,
14 clusters. **Decision: NO-GO. Do not enable D/E/F.1.** The C resolver did not execute on exact
eligible input; safety is intact but the headline resolver is not live.

**Decisive evidence — 71 watches were the exact C-eligible golden-reference input, yet stayed generic:**

```text
Expected (C active)                    Observed (this capture)
-----------------------------------    -----------------------------------
raw_direction       = BUY              raw_direction       = BUY
price_position      = MAIN_RESISTANCE  price_position      = MAIN_RESISTANCE
phase_priced        = RESISTANCE_PRESSURE_WARNING (both)
pattern             = UPPER_ABSORPTION_WARNING / NO_NEW_BUY / PROTECT_LONG_OR_SELL_WATCH (both)
signal_family       = MICROBOOST_COUNTER_ENTRY     signal_family       = MICROBOOST_WATCH
status              = EARLY_SELL_WATCH             status              = MICROBOOST_WATCH
candidate_direction = SELL                         candidate_direction = BUY
resolved_family / scenario_resolver / headline_resolve_reason : ABSENT (0/168)
```

`candidate=BUY` + generic reason + zero resolver fingerprints is exactly what **C-flag-OFF** looks like
on a build that contains the C code. Cause is Railway-side (flag not set on the running deployment, or
the deployed commit predates C) — not a confirmed code bug (the golden tests prove the code resolves
this input).

**Safety status (PASS):** `[SignalJSON]` = 0 · `valid_for_execution=true` = 0 · `is_final_signal` = 0 ·
`final_direction=WAIT` 168/168.

**Positive runtime findings (this deployment is newer than the baseline):**

```text
raw_direction propagation healthy : 163/168 (97%) watches carry raw_direction
phase_priced present              : 163/168
market_context / pattern_context / execution_gate : all attached
```

**E preview (not yet enabled):** 14 clusters carry 168 watches; **151/168 (90%) emits are
semantic-duplicates** E would suppress (top clusters: GBPNZD 41, GBPJPY 40, CADCHF 36, GBPCHF 28).

**Required next action:** (1) verify Railway runs `152b5ff0+` (min `91cf167c+`); (2) set
`SIGNAL_WATCH_PATTERN_HEADLINE_RESOLVE_ENABLED=true` on the active service; (3) redeploy if the env
change did not trigger one; (4) run 15–30 min; (5) export + re-run the freshness gate; (6) Stage-1 GO
only when eligible MAIN_RESISTANCE/MAIN_SUPPORT events resolve to directional watch families while
`[SignalJSON]` stays flat.

---

## Stage-1 attempt #2 ledger — the deployment-mixing trap

Second gate-passing capture (`logs.1781147630898.json`): sha256 `a9e5a6bc…`, event-max
`2026-06-11 02:11 UTC` (beats #1), 334 `[SignalWatchJSON]` / 16 symbols / 27 clusters. It PASSES
freshness (new hash + later window) but **FAILS as rollout proof** — the export mixes **13 Railway
deployment ids**. **Decision: NO-GO — invalid rollout proof; inconclusive on the current live deployment.**

Split by deployment (newest event first), every segment resolved zero:

```text
deployment   watches   newest event        eligible(MAIN_RES+WARN)   resolved
7eba79f4        9      2026-06-11 02:11          0                      0    <- NEWEST / live
698afcfb       44      2026-06-10 08:35         44                      0
820919d9       40      2026-06-10 13:23         40                      0
e6ab509b       31      2026-06-10 09:16         28                      0
... (13 deployments total)                     121 eligible            0
```

Correct reading (do NOT overclaim):
- C is **confirmed OFF** on the older deployments that carried eligible cases (`698afcfb`/`820919d9`/`e6ab509b`
  had 44/40/28 exact golden inputs, incl. 83 nested `UPPER_ABSORPTION_WARNING`, all stayed generic).
- The **newest/live deployment `7eba79f4` is UNPROVEN** — 9 watches, **0 eligible** events to resolve;
  the overnight window contained no `MAIN_RESISTANCE+RESISTANCE_PRESSURE_WARNING` event.

**Safety (PASS):** `[SignalJSON]`=0 · `valid_for_execution=true`=0 · `final_direction=WAIT` 334/334 · `is_final_signal`=0.

**Lesson → Evidence Gate v2:** a fresh hash is necessary but NOT sufficient. A fresh *mixed-deployment*
export is still invalid rollout evidence. The gate below now rejects any sample spanning >1 deployment.

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

Then count distinct deployments — a fresh hash over a *mixed-deployment* export is still invalid proof
(attempt #2 mixed 13 deployments):

```powershell
# Gate 2 — single deployment (deployment id lives in the Railway tags JSON, often escaped as \"deployment\")
$deps = [regex]::Matches($raw, 'deployment\\?"\s*:\s*\\?"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})') |
  ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
"deployment_id_count = $($deps.Count)"
$deps
if ($deps.Count -ne 1) { "REJECT for rollout proof — export mixes $($deps.Count) deployments" }
```

### Evidence Gate v2 — a sample is valid for GO/NO-GO only if ALL gates pass

```text
Gate 1  Freshness            sha256 != last accepted hash; event_max > last accepted event_max; rows > 0
Gate 2  Single deployment    deployment_id_count == 1   (>1 -> REJECT for proof; exploratory analysis only)
Gate 3  Deployment identity  that one id == current active Railway deploy; running_commit >= 152b5ff0
                             (min 91cf167c); the stage flag is set on THAT deploy
                             (Stage 1: SIGNAL_WATCH_PATTERN_HEADLINE_RESOLVE_ENABLED=true)
Gate 4  Eligibility          >=1 watch with raw_direction in {BUY,SELL}
                             + price_position in {MAIN_RESISTANCE, MAIN_SUPPORT}
                             + phase_priced in {RESISTANCE_PRESSURE_WARNING, SUPPORT_PRESSURE_WARNING}
                             golden: BUY + MAIN_RESISTANCE + RESISTANCE_PRESSURE_WARNING
Gate 5  Safety               [SignalJSON]=0 (unless intentionally testing final); valid_for_execution=true=0;
                             final_direction=WAIT for all watches; is_final_signal=true=0
```

**Stage-1 decision rules:**

```text
freshness fails                                  -> REJECT SAMPLE
deployment_count > 1                             -> REJECT SAMPLE (proof); exploratory only
current deploy has 0 eligible cases              -> INCONCLUSIVE (extend window / active session)
eligible cases present + resolver fingerprints   -> GO   (EARLY_*_WATCH / resolved_family present)
eligible cases present + NO resolver fingerprints -> NO-GO (C inactive / code path not executing)
```

The key correction: **fresh hash alone is not enough — a fresh mixed-deployment log can still be invalid
rollout evidence.** Record all values in the ledger below before accepting any sample.

| Sample | Railway deployment/commit | C flag | Content hash | Event window UTC | Verdict |
|---|---|---|---|---|---|
| Current duplicate baseline | Not established by capture | Not evidenced | Reported MD5 prefix `6160fca6` | 2026-06-10 02:58-15:53 | Baseline only |
| post-C attempt #1 (`…142295337`) | Unknown — verify Railway commit (expect `152b5ff0+`) | Not effective (resolver idle → likely OFF) | `sha256:65cc2e5e…` | 2026-06-10 08:35 → 2026-06-11 01:44 | **NO-GO — C not active** |
| post-C attempt #2 (`…147630898`) | MIXED — 13 deployments (newest `7eba79f4`) | Unknown per-deploy | `sha256:a9e5a6bc…` | up to 2026-06-11 02:11 | **NO-GO — invalid proof (deployment mixing); live deploy unproven** |
| Required post-C capture (GO) | single id == active deploy, `152b5ff0+` | `true` on THAT deploy | new SHA-256 | max later than 2026-06-11 02:11 | Pending — needs `deployment_count==1` + ≥1 eligible |

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
