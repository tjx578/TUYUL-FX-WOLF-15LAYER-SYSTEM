# Wolf15 SignalThrottle Golden Pattern Database

This folder stores analysis-layer pattern metadata for SignalThrottle pressure.
The registry never executes trades and never overrides Constitution/L12.

Golden references are evidence sources, not pair locks. A pattern ID describes
a universal market condition; public SignalJSON emits these as
`reference_cases[]` while older internal objects may still expose
`golden_reference` / `golden_references` for compatibility. Pair names add
calibration such as pip size, spread, session behavior, volatility, and
optional basket metadata.

Core rule:

```text
SignalThrottle = pressure radar.
Microboost = priority/lifecycle booster.
Allowed = provisional direction.
Final direction requires phase, price context, risk, lifecycle, spread, and tradeplan readiness.
Basket/theme context is optional calibration and debug metadata, not a production gate.
```

Historical audits such as CHFJPY are stored as universal reference cases. A
validated JPY basket follow-through can upgrade a theme alert into recognized
pattern context, but fragmented basket rotation, MTF pullback decision states,
late-session expansion failure, and zero-drawdown follow-through remain
watch/validation context until the live pair has its own phase, trigger, risk,
and execution contract.

Use `analysis.signalthrottle_patterns.match_golden_patterns()` to enrich live
features with:

- `selected_pattern_id`
- `matched_patterns`
- `pattern_tier`
- `pattern_family`
- `pattern_score`
- `pattern_match_score`
- `execution_readiness_score`
- `pattern_scope`
- `applies_to`
- `reference_cases`
- `pair_calibration`
- `pattern_context`
- `tradeplan_preview`
- `execution_gate`
- `lifecycle`
- `pattern_search_space`
- `pattern_db_candidates_scanned`
- `pattern_db_exact_matches`
- `pattern_db_fuzzy_matches`
- `pattern_bottlenecks`
- `pattern_match_diagnostics`
- `entry_permission`
- `management_action`
- `hold_policy`
- `chase_allowed`
- `block_reason`
- `target_source`

Compatibility fields such as `golden_reference`, `golden_references`,
`pair_specific_calibration`, and `pair_role` may still exist inside internal
Python objects for older callers. Emitted SignalJSON payloads should treat
`reference_cases[]` and `pair_calibration{}` as the public identity contract:
reference cases are historical proof only, while the live symbol is calibrated
from current pair context.

`pattern_match_score` describes how strongly the historical/golden pattern is
recognized. `execution_readiness_score` describes whether the current market
context is ready for execution. `pattern_score` remains as a backward-compatible
readiness score and should not be used alone to downgrade a Tier-S pattern.

The matcher now runs a database-wide retrieval pass across every
`GOLDEN_PATTERNS` entry. Exact IDs from prior logs or nested
`pattern_context` win first; semantic/fuzzy matches are lower-weight support
signals. `pattern_bottlenecks` explains why a recognized watch pattern did not
become a final SignalJSON, for example provisional RR fallback targets,
missing support/resistance ladders, RR below minimum, ambiguous price phase,
lifecycle conflict, or specific counter/reversal confirmation gates.

Production SignalJSON uses `SIGNAL_JSON_COMPACT_PRODUCTION=true` by default.
That keeps the public log focused on core identity, direction state, nested
`pattern_context`, `tradeplan_preview`, `execution_gate`, and
`lifecycle`, while dropping null placeholders and duplicated flat pattern/theme
fields. The full `matched_patterns` scan ledger is also debug-only in compact
production logs; the main `pattern_context` keeps `candidate_patterns_count`,
evidence-backed `confirmed_patterns`, and `top_supporting_patterns`. Heavy
matcher internals such as fuzzy matches, semantic hits, candidate score maps,
and the full matched-pattern ledger are emitted only when
`SIGNAL_JSON_PATTERN_DEBUG_ENABLED=true` creates a separate
`PatternMatchDebugJSON` sidecar.

Watch events must expose `watch_direction` while keeping
`validated_direction=None` until structure, confirmation mode, and execution
readiness are all satisfied. M15 close is only mandatory for ambiguous,
counter, reversal, or lifecycle-conflict paths; direct absorption can bypass it
when structure target, RR, phase, lifecycle, and spread gates are complete.

SignalWatchJSON also carries an `operator_tradeplan` summary when HTF context is
available. This is deliberately short: pressure, memory bias/phase, D1/H4
location, setup, wait condition, and reason. D1/H4 are the structure map for
watch planning; M15 is reported as `TIMING_CONFIRMATION_ONLY` and never becomes
the source of structural SL/TP authority. The summary is read-only and always
keeps `execution_allowed=false` until the normal SignalJSON firewall promotes a
separate execution-grade payload.

Actionable preview levels are only displayed when the watch location is
confirmed by HTF structure: H4 demand/supply zone, H4 swing invalidation, a
valid target ladder, and Daily fib/key-level confluence. When pressure exists
but the HTF trade location is not confirmed, the operator setup remains
`BUY_STRUCTURE_WATCH` / `SELL_STRUCTURE_WATCH`, entry/SL/TP are omitted, and
`wait_for` is `H4_DAILY_STRUCTURE_AND_M15_TIMING`.

Scanner-cycle clean blocks remain non-primary authority. A mature scanner-cycle
memory block can emit an advisory `SignalWatchJSON` only when market context is
available and `SIGNAL_THROTTLE_SCANNER_MEMORY_ADVISORY_WATCH_ENABLED=true`
with the configured maturity thresholds met. These watches carry
`watch_scope=SCANNER_CYCLE_MEMORY_ADVISORY`,
`eligible_for_primary_watch=false`, and `valid_for_execution=false`; they exist
to prevent strong pressure memory from going silent, not to bypass L12 or the
SignalJSON execution firewall.

`pattern_registry.yaml` and `pair_role_map.yaml` are the operational database.
`reference_cases.yaml` stores historical pair windows as evidence sources, and
`historical_validation_log.yaml` records what each upload proved or corrected.
`registry.py` loads the operational YAML at runtime and falls back to the static
Python copy only if YAML loading is unavailable, so matcher behavior and
reviewed database content stay aligned.
