# Microboost Pure-Stage Contract

Status: architecture contract. The Microboost detector already implements this
boundary; this file records the **output/field contract** that the detector and
any Microboost emitter must preserve.

Companion document:
[signal-throttle-microboost-radar-contract.md](signal-throttle-microboost-radar-contract.md)
defines the *lifecycle* boundary ("Microboost is a radar that lives from the
pressure stream, not a child of `EXECUTE_*`"). **This** document defines the
*field/output* boundary: what a Microboost core event may and may not carry.

## Verdict utama

Microboost = **timing evidence** pada pair yang sudah lolos SignalThrottle clean
block. Bukan direction resolver, bukan pattern engine, bukan trade plan, bukan
execution gate.

```text
SignalThrottle  = pair valid (clean block).
Microboost      = timing valid + lokasi.
SignalWatch/Decision = arah & strategi.
SignalJSON      = eksekusi.
```

Microboost menjawab hanya empat hal: **pair clean-block mana**, **timing burst
seperti apa**, **muncul di lokasi mana**, dan **apakah masih butuh price
context**. Tidak lebih.

## Sudah benar di kode (jangan ditulis ulang)

- Timing murni tanpa harga: `_classify_unpriced_phase`
  (`analysis/microboost_detector.py`) → `IGNITION/DENSE/REPEATED/NEAR_TIMING_GATE_MICROBOOST`
  dari duration/density/recurrence saja.
- Makna berbasis lokasi: `_structure_microboost_phase`
  (`analysis/microboost_detector.py`):
  - `MAIN_SUPPORT + BUY` → support bounce (buy timing evidence)
  - `MAIN_RESISTANCE + BUY` → exhaustion / pressure warning (no-buy-chase decision)
  - `MAIN_RESISTANCE + SELL` → rejection evidence
  - `MID_RANGE` / late extension → wait / management
- Gerbang clean-block: `_signal_watch_gate`
  (`analysis/signal_throttle_log_analyzer.py`) menolak microboost yang pair-nya
  bukan clean-block candidate:
  - tanpa candidate → `SIGNAL_THROTTLE_CLEAN_BLOCK_REQUIRED`
  - pair beda → `MICROBOOST_PAIR_NOT_CLEAN_BLOCK_CANDIDATE`
  - arah beda → `MICROBOOST_DIRECTION_NOT_CLEAN_BLOCK_DIRECTION`

  Microboost tidak boleh memilih pair sendiri.

## Core event contract

Canonical compact event (`analysis/microboost_core_event.py`,
`to_microboost_core_event`):

```json
{
  "event": "microboost_qualified",
  "schema_version": "1.0",
  "symbol": "USDCAD",
  "direction": "UNRESOLVED",
  "raw_pressure_direction": "BUY",
  "phase_unpriced": "REPEATED_MICROBOOST",
  "phase_priced": "RESISTANCE_PRESSURE_WARNING",
  "price_position": "MAIN_RESISTANCE",
  "start_utc": "2026-05-21T03:30:06Z",
  "end_utc": "2026-05-21T03:33:08Z",
  "duration_minutes": 3.04,
  "effective_tick_count": 138,
  "effective_density_per_minute": 45.45,
  "requires_market_context": true,
  "valid_for_execution": false,
  "next_stage": "SIGNAL_WATCH",
  "reason": "Microboost timing evidence; strategy decision delegated to SignalWatch/SignalDecision."
}
```

### Invariants (wajib)

```text
direction            = "UNRESOLVED"     (selalu)
valid_for_execution  = false            (selalu)
next_stage           = "SIGNAL_WATCH"   (selalu)
```

`raw_pressure_direction` (`BUY`/`SELL`/`NONE`) menyimpan warna tekanan mentah —
arah entry tetap diputuskan oleh layer hilir, bukan Microboost. Makna lokasi
dibawa oleh `phase_priced` + `price_position`, bukan oleh sebuah arah final.

### Allowlist vs downstream metadata

Core event dibangun **hanya** dari `MICROBOOST_CORE_EVENT_FIELDS`. Field berikut
adalah **pass-through dari validator hilir** (`validate_market_context`) dan
**dilarang** muncul di Microboost core stream — tempatnya di
`market_context_validation` atau debug stream `[PatternMatchDebugJSON]`:

```text
pattern_family, pattern_score, pattern_tier, pattern_match_score,
matched_patterns, selected_pattern_id, execution_readiness_score,
golden_reference, golden_references, pattern_scope, pattern_evidence,
pattern_search_space, pattern_db_*, pattern_match_diagnostics,
entry_permission, management_action, hold_policy, chase_allowed, block_reason,
strategy_pattern, execution_side, pair_specific_calibration,
jpy_alignment_status, theme_alignment_status, dual_theme_status,
score, score_components, market_context_snapshot
```

Daftar lengkap: `MICROBOOST_DOWNSTREAM_METADATA_FIELDS` di
`analysis/microboost_core_event.py`. Karena core event dibangun dari allowlist,
field-field ini tidak akan pernah bocor walau ada di object internal.

## Yang dilarang di pure-stage

Jangan membuat di layer Microboost: `MicroboostDirectionResolver`,
`MicroboostTradePlanBuilder`, `MicroboostSignalJSONEmitter`,
`MicroboostPatternEngine`, atau execution gate. Microboost cukup sampai
`next_stage = SIGNAL_WATCH`.

Kalimat paling tajam:

```text
Core Microboost sudah benar.
Yang dijaga adalah batas output-nya: timing + lokasi, arah UNRESOLVED, eksekusi ditolak.
```
