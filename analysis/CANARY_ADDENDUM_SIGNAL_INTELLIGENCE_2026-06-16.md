# Signal Intelligence Completion — Canary Addendum

```text
Sprint area : SIGNAL_INTELLIGENCE_COMPLETION
Scope       : #1 Direction Recovery + #2 Family Lineage + #3/#4 Tradeplan Coverage Unlock
Mode        : Single-deployment observability canary
Execution   : Locked / no execution expansion
Recorded    : 2026-06-16 (branch main)
```

## 1. Grounded Finding
```text
#2 Family lineage: source_family/source_stage/resolved_family/family_lineage_reason
   absent in DecisionUpdate baseline (0/1484). Code fixed, dormant, canary-ready.
#3/#4 Tradeplan + market_structure: directional watches already carry rich NESTED
   tradeplan_preview + market_structure (entry_zone, sl, invalidation, tp1, rr, structure_class,
   market_structure_status, execution_usable=false). Largely shipped.
Bottleneck: directionless MICROBOOST_WATCH (14/44) cannot form structure bias or tradeplan.
   -> direction recovery canary required.
```
Key conclusion: **the next bottleneck is direction recovery, not tradeplan generation.** When
direction is available, tradeplan_preview + market_structure extend automatically to more watches.

## 2. Objective
Prove dormant direction/lineage observability improves coverage WITHOUT changing execution:
```text
1. direction recovery fields populated
2. DecisionUpdate lineage fields populated
3. directionless MICROBOOST_WATCH count decreases
4. more watches receive tradeplan_preview + market_structure
5. no false SignalJSON / valid_for_execution=true introduced
```

## 3. Canary flags — the ONLY three to enable
```env
SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS=true
MICROBOOST_WATCH_MISS_DIRECTION_RECOVERY_ENABLED=true
SIGNAL_FAMILY_LINEAGE_ENABLED=true
```
Each touches a DISTINCT field/event (clean attribution even together). Keep everything else unchanged.

## 3a. Flag reconciliation — VERIFIED against code (supersedes any other flag block)
The original "execution safety" list contained name/default errors. Verified truth:

| Intended flag | Code reality | Action |
| --- | --- | --- |
| `SIGNAL_JSON_STRICT_LIFECYCLE` | EXISTS, default **true** (pipeline:419) | already safe — confirm, no change |
| `SIGNAL_JSON_FINAL_BARRIER_ENABLED` | EXISTS, default **true** (gate_adapter:42) | already safe — confirm, no change |
| `SIGNAL_JSON_EXEC_GATES_ENFORCE` | EXISTS, default **true** (gate_adapter:44) | already safe — confirm, no change |
| `SIGNAL_JSON_REQUIRE_TERMINAL_DECISION_UPDATE` | EXISTS, default **true** | already safe — confirm, no change |
| `SIGNAL_JSON_EXECUTION_GATES_ENFORCE` | **WRONG NAME** | use `SIGNAL_JSON_EXEC_GATES_ENFORCE` (already true) |
| `SIGNAL_JSON_ALLOW_PROVISIONAL_RR_EXECUTION` | **DOES NOT EXIST (phantom)** | DO NOT set — it is a no-op. Provisional-RR is already hard-BLOCKED in code (exec-safety patch); no env flag re-opens it |
| `SIGNAL_JSON_REQUIRE_PARENT_WATCH` | EXISTS, default **false** | setting true = a CHANGE (stricter) — optional hardening, NOT "unchanged" |
| `SIGNAL_JSON_ALLOW_DIRECT_BYPASS` | EXISTS, default **true** | setting false = a CHANGE (stricter) — optional hardening, NOT "unchanged" |
| `SIGNAL_JSON_REQUIRE_FINAL_MARKET_STRUCTURE` | EXISTS, default **false** | setting true = a CHANGE (stricter) — optional hardening, NOT "unchanged" |

**Recommendation (cleanest canary):** change ONLY the three §3 observability flags; leave execution
flags at their current protective defaults. This keeps execution behaviour byte-identical and makes
the three observability flags the ONLY variables. If extra hardening is desired, the three "stricter"
flags may be set deliberately — but record them as intentional changes in the ledger, not as "unchanged".

## 4. Capture rules
```text
1. Single deployment only (multiple deployment IDs -> INVALID).
2. Fresh capture after canary deploy.
3. Min 6h, ideal 23h.
4. Must include eligible SignalThrottle / Microboost / DecisionUpdate events.
5. No mixed old deployments.
6. Record deployment ID, commit hash, flag state, start/end UTC, content hash.
Newest deployment with zero eligible events -> INCONCLUSIVE, not PASS.
```

## 5. Baseline (previous 23h capture)
```text
MicroboostWatchDiagnostic direction_recovery_source : 0 / 499
DecisionUpdate lineage fields                       : 0 / 1484
SignalWatch total                                   : 44
Directional watches with tradeplan/structure         : 30 / 44
Directionless watches without tradeplan/structure    : 14 / 44
SignalJSON final                                    : 0
valid_for_execution=true                            : 0
```

## 6. Acceptance — PASS only if ALL true
```text
A. direction_recovery_source appears in MicroboostWatchDiagnostic
B. source_family appears in SignalDecisionUpdateJSON
C. source_stage appears in SignalDecisionUpdateJSON
D. resolved_family appears in SignalDecisionUpdateJSON
E. family_lineage_reason appears in SignalDecisionUpdateJSON
F. raw_direction null share decreases vs baseline
G. directionless MICROBOOST_WATCH count decreases vs baseline
H. more watches gain tradeplan_preview and/or market_structure
I. SignalJSON stays 0 unless a fully execution-grade signal appears
J. valid_for_execution=true stays 0 unless all execution gates are truly valid
K. no increase in contradictory payloads
L. no parser/dashboard failure from added fields
```

## 7. NO-GO if ANY occurs
```text
1. mixed deployment export
2. SignalJSON with execution_valid_now=false
3. valid_for_execution=true while tradeplan_context_ready=false
4. PROVISIONAL_RR_FALLBACK becomes execution-usable
5. DecisionUpdate count explodes abnormally
6. Watch count explodes abnormally
7. lineage fields appear but source_family/resolved_family generic/misleading for ALL events
8. direction recovery populates direction against price phase, low confidence, no diagnostic reason
9. dashboard/parser breaks due to new fields
```

## 8. INCONCLUSIVE (not fail — rerun on eligible window)
```text
1. fresh deployment has no eligible Microboost / DecisionUpdate events
2. capture too short to observe canary paths
3. market closed / weekend noise dominates
4. provider/log-sync noise dominates, no real signal-runtime path
```

## 9. Rollout ledger
| Attempt | Deploy ID | Commit | Flags | Capture UTC | Duration | Deploy count | Eligible events | Result | Verdict |
| --- | --- | --- | --- | --- | --: | --: | --: | --- | --- |
| canary-1 | TBD | TBD | direction + miss-recovery + lineage ON | TBD | TBD | 1 required | TBD | TBD | TBD |

## 10. Post-canary decision
```text
PASS:  #1 = CANARY_VALIDATED ; #2 = CANARY_VALIDATED ;
       #3/#4 = EXTENDED_BY_DIRECTION_RECOVERY ; next = #5 Decision Validator
NO-GO: rollback flags to false ; do NOT revert dormant code unless schema/emitter failure confirmed ;
       patch only the failing attribution path
INCONCLUSIVE: keep code dormant ; rerun on eligible market window
```

## 11. Final safety rule
Observability/intelligence only. Must NOT: open execution, increase order permission, weaken
SignalJSON strict lifecycle, allow provisional-RR execution, or promote WATCH into executable
SignalJSON without complete tradeplan + execution gates.

```text
Run canary only after this addendum is recorded. Single deployment. No mixed export. No execution change.
```

> Context: prior rollout proof went NO-GO due to a 13-deployment mixed export — hence the hard
> Freshness + Single-Deployment + Eligible-Case gate. Lineage/direction enrichment is locked as
> observability, never an execution trigger.
