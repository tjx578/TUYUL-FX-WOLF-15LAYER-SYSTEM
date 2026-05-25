# SignalJSON Structure-Aware Counter-Entry Contract

## Scope

This contract applies to `MICROBOOST_COUNTER_ENTRY` results produced from a
priced microboost warning at key structure. It separates analysis validity from
immediate execution readiness. The `TP1 >= 2.0R` execution invariant applies
to all final SignalJSON families, including trend-continuation and
breakout/breakdown continuation events.

## Repository Assessment

Before schema version `1.1-structure-aware`, the counter-entry path already
detected resistance/support rejection and exported several flat structure
fields. It had four execution weaknesses:

1. RR validation used `sl_tight` while a safer `sl_safe` value was available.
2. `tp1..tp4` were treated uniformly, so a nearby low-RR support could appear
   as the first executable profit target.
3. The pipeline extended an observed ladder into synthetic levels to fill four
   target slots.
4. Finality gates accepted `valid_for_execution=true` without requiring
   numerical invalidation, risk, zones, or selected targets.

## Target And Stop Policy

For counter-entry signals:

- `selected_sl_mode` defaults to `SAFE` when `sl_safe` is available.
- `risk_pips`, `selected_risk_pips`, and RR validation use `selected_sl`.
- `TP1` is mandatory and calculated at `SIGNAL_JSON_TP1_RR_REQUIRED`,
  default `2.0R`; configuration cannot reduce this execution floor below
  `2.0R`.
- `TP2+` are optional and only exported from observed M15/H1 structure levels
  beyond TP1; no extrapolated ladder levels qualify.
- A counter-entry final execution still requires an observed structure target
  reaching `SIGNAL_JSON_MIN_RR_VALID`, default `2.5R`.
- A structure target too close to TP1 is suppressed when separated by less
  than `0.20` of initial risk.

This preserves the existing executor configuration `TP1_ONLY` while exporting
auditable extension targets for management and dashboards.

For `MICROBOOST_TREND_CONTINUATION`, TP1 is also canonicalized to fixed `2.0R`.
Nearby observed structure remains useful as reclaim context, but is not
exported as an executable TP1 when its reward is below the floor. Continuation
RR fallback ladders now begin at `2.0R` rather than `1.0R`.

## Final Execution Gate

`execution_valid_now=true` is allowed only when all of the following are true:

- A relevant rejection/support zone, `key_resistance`, and `key_support` exist.
- Entry zone, selected SL, selected risk, hard invalidation, and canonical
  targets are present.
- An observed structure target reaches the configured final RR threshold.
- M15 rejection/direct absorption confirmation has been obtained.
- Spread is available and accepted by the existing market-context spread gate.
- H1 is not explicitly directional against the counter-entry.

The emitter, signal lifecycle manager, and pending-block finalizer enforce the
same minimum TP1 invariant; the constitutional RR gates are also aligned to
`2.0R` for every volatility regime. A manually formed legacy payload can no
longer become final solely by setting `valid_for_execution=true`.

## Exported Objects

The event schema exports:

- `target_policy` and `targets`
- `structure_zones`
- `risk_reward`
- `invalidation_rules`
- `execution_quality`
- `phase_coherence`
- `signal_expiry`
- `analysis_valid`, `tradeplan_valid`, `execution_valid_now`, and
  `execution_status`

## Available And Unavailable Evidence

The current live pipeline can derive M15/H1 (and record H4 when present),
observed support/resistance ladders, tick spread, and configured normal spread
limits. It does not yet supply authoritative currency-strength ranks, scored
historical touch/freshness metadata, volume/POC levels, or a calibrated
multi-timeframe coherence score. Those fields must not be populated with
guessed values; they require a separate data-source and scoring implementation.

## AUDNZD Audit Fixture

The regression fixture for AUDNZD uses the submitted levels as an input
scenario, not as a claim about a currently verified live quote. With entry
`1.22158`, safe SL `1.22375`, and pip size `0.0001`, the contract calculates:

- selected risk: `21.7` pips
- mandatory TP1 at 2R: `1.21724`
- observed structure extensions: `1.21562`, `1.21492`

When the fixture reports a `4.0` pip spread above its accepted spread gate, the
analysis and tradeplan remain valid but the output is
`WAIT_SPREAD_NORMALIZATION`, not a final execution signal.
