# Pressure Radar Gate v1 — Production Log Validation

Status: replay-validated, non-executable foundation

Source window: 2026-07-20 06:51:20–07:21:20 UTC

Gate: `pressure_radar_gate_v1`

## Dataset and grain

The source file is a Railway JSON export with SHA-256:

```text
e4f3dbc779ee17ed719178f7d26668d5c58c726120d79c4a7b4592a4318915f3
```

It contains 413 `SignalPressureStateJSON` records across two deployments. The
first 111 records belong to deployment `43ce34d6…` at main commit `9244f60b…`.
They must not be joined to the requested window. The validated segment is:

```text
records       302
symbols        19
deployment    916abb83-e85e-4ff8-a110-beedcac619b8
commit        da0d1332ced8fa6947392897db3fc98e183846a2
replicas        1 distinct replica
parse errors    0
duplicates      0 exact payload duplicates
```

Replay is therefore deployment-scoped. Combining the two deployments produces
an incorrect eleventh candidate from the older GBPUSD lifecycle.

## Frozen predicate

The selector reads `direction_next_required_stage`, not the general
`next_required_stage` field:

```python
stage_ok = (
    source_stage in {"PRESSURE_BLOCK", "CANDIDATE_LIFECYCLE"}
    or (
        signal_family == "SIGNAL_THROTTLE_ALLOWED_QUORUM"
        and pair_eligible_for_analysis is True
    )
)

analysis_candidate = (
    raw_direction_eligible_for_context_resolution is True
    and current_block_effective_ticks >= 3
    and stage_ok
    and htf_structure_context.daily_bias_freshness_status == "FRESH"
    and htf_structure_context.allowed_playbook != "NONE"
    and direction_next_required_stage == "LIQUIDITY_ACCEPTANCE_OR_REJECTION"
)
```

All 302 target records pass the raw-direction, freshness, playbook, and
direction-next-stage predicates. In this window the effective selection is
therefore `ticks >= 3` plus the allowed stage. Eleven symbols reach three
ticks; GBPUSD alone fails the stage predicate and remains
`RESERVE_NEAR_QUALIFIED`.

## Candidate and lineage results

The gate produces exactly ten provisional candidates: 7 BUY, 3 SELL, with 3
`PRESSURE_BLOCK`, 6 `CANDIDATE_LIFECYCLE`, and 1 `ALLOWED_QUORUM`.

| Symbol | Raw | Stage | Qualifying UTC | Lineage UTC | Delay s | Clean block |
| --- | --- | --- | --- | --- | ---: | --- |
| AUDUSD | BUY | PRESSURE_BLOCK | 06:51:23.937946 | 06:57:43.910325 | 379.972 | `AUDUSD_20260720T065123Z_20260720T065623Z` |
| EURGBP | SELL | PRESSURE_BLOCK | 06:51:26.236846 | 06:57:45.253223 | 379.016 | `EURGBP_20260720T065125Z_20260720T065625Z` |
| NZDUSD | BUY | PRESSURE_BLOCK | 06:51:26.930659 | 06:56:24.098206 | 297.168 | `NZDUSD_20260720T065044Z_20260720T065544Z` |
| EURAUD | SELL | CANDIDATE_LIFECYCLE | 06:51:30.561597 | 06:57:32.626785 | 362.065 | `EURAUD_20260720T065129Z_20260720T065629Z` |
| GBPJPY | BUY | CANDIDATE_LIFECYCLE | 06:51:33.608484 | 06:57:34.274720 | 360.666 | `GBPJPY_20260720T065132Z_20260720T065632Z` |
| GBPNZD | SELL | CANDIDATE_LIFECYCLE | 06:51:37.344223 | 06:57:49.537941 | 372.194 | `GBPNZD_20260720T065135Z_20260720T065635Z` |
| AUDJPY | BUY | CANDIDATE_LIFECYCLE | 06:51:39.586981 | 06:57:36.390959 | 356.804 | `AUDJPY_20260720T065137Z_20260720T065637Z` |
| AUDCHF | BUY | CANDIDATE_LIFECYCLE | 06:51:42.343230 | 06:57:37.776696 | 355.433 | `AUDCHF_20260720T065140Z_20260720T065640Z` |
| NZDJPY | BUY | CANDIDATE_LIFECYCLE | 06:51:42.781436 | 06:57:38.572186 | 355.791 | `NZDJPY_20260720T065141Z_20260720T065641Z` |
| NZDCHF | BUY | ALLOWED_QUORUM | 06:51:43.297763 | 06:59:56.468541 | 493.171 | `NZDCHF_20260720T065141Z_20260720T065641Z` |

All ten clean-block intervals contain their qualifying timestamps and preserve
raw direction, daily bias, H4 structure, price location, liquidity resolution,
and allowed playbook. Delay is 297.168–493.171 seconds, median 361.366 seconds.

`context_version` does **not** remain equal: all ten lineage events carry a new
version because volatile snapshot/age fields participate in its upstream hash.
Deferred association therefore uses a stable structural-context signature and
stores qualifying and lineage context versions separately.

## State and safety contract

```text
RADAR_OBSERVED
→ RADAR_QUALIFIED_PROVISIONAL
→ WAITING_CANONICAL_LINEAGE
→ ANALYSIS_READY
→ CLOSED_CANDLE_EVIDENCE
```

The assembler latches the first qualification, maximum effective ticks, and
highest allowed stage. A later one-tick row cannot erase that history. It only
attaches lineage when deployment, symbol, direction, clean-block interval, TTL,
and stable structural context agree. Direction reversal or TTL expiry closes
the provisional lifecycle.

Every manifest remains:

```text
final_direction     WAIT
valid_for_execution false
is_final_signal     false
```

The gate never ranks candidates and never claims directional accuracy. Tier or
market-priority ordering belongs to the future closed-candle evidence layer.

## Reproduction

```powershell
python -m services.pressure_outbox.radar_replay `
  "C:\Users\INTEL\Downloads\logs.1784538164760.json" `
  --deployment-id 916abb83-e85e-4ff8-a110-beedcac619b8
```

## Limits

All ten qualifications occur during the first 19.360 seconds of the target
deployment. This window validates deterministic selection and lineage recovery,
but does not establish precision/recall, H1/M15 setup quality, trade outcome, or
behavior outside a cold-start burst. The gate requires validation on a
no-restart window before production activation.
