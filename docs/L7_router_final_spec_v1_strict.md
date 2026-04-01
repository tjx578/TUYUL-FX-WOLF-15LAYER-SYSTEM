# L7 Router Final Spec v1 — Strict Constitutional Mode

## Tujuan

L7 adalah **probability / survivability legality governor** untuk Phase 3.  
L7 menerima propagasi legal dari **Phase 2.5 / upstream wrapper** dan menilai apakah
kondisi probabilistik, edge availability, dan validation envelope masih cukup layak
untuk diteruskan ke **L8**.

L7 **bukan**:

- decision engine
- execution authority
- sizing module
- final verdict router

## Authority Boundary

L7 hanya boleh mengeluarkan:

- status legality: `PASS | WARN | FAIL`
- continuation legality ke `L8`
- score band / score numeric
- blocker / warning codes
- audit trail
- feature envelope untuk replay / backtest / pattern mining

L7 tidak boleh mengeluarkan:

- `direction`
- `execute`
- `trade_valid`
- `position_size`
- `final_verdict`

## Evaluasi Inti

L7 mengevaluasi:

1. upstream legality dari wrapper sebelumnya
2. availability sumber probabilistik / edge yang wajib
3. probability legality
4. edge validity / validation availability
5. fallback legality
6. compression ke `PASS/WARN/FAIL`
7. continuation legality ke `L8`

## Canonical Score

Field numerik utama L7 adalah:

`score_numeric := win_probability`

Interpretasi:

- representasi mutu survivability/probability envelope
- bukan jaminan trade
- bukan final composite score
- dipakai hanya untuk legality envelope L7

## Coherence Band untuk L7

Agar envelope tetap seragam lintas layer, field band tetap memakai nama:

`coherence_band`

Tetapi di L7 maknanya adalah **probability band**.

Threshold baseline:

- `HIGH >= 0.67`
- `MID >= 0.55 and < 0.67`
- `LOW < 0.55`

## Critical Blockers

Hard fail L7:

- `UPSTREAM_NOT_CONTINUABLE`
- `REQUIRED_PROBABILITY_SOURCE_MISSING`
- `EDGE_VALIDATION_UNAVAILABLE`
- `EDGE_STATUS_INVALID`
- `WIN_PROBABILITY_BELOW_MINIMUM`
- `FRESHNESS_GOVERNANCE_HARD_FAIL`
- `WARMUP_INSUFFICIENT`
- `FALLBACK_DECLARED_BUT_NOT_ALLOWED`
- `CONTRACT_PAYLOAD_MALFORMED`

## Warning Envelope

Non-fatal degradation yang boleh menghasilkan `WARN`:

- `STALE_PRESERVED`
- `PARTIAL` warmup
- legal emergency fallback
- probability band `MID`
- edge status degraded
- confidence validation partial
- low sample count but still legal

## Compression Rules

### PASS

Diberikan bila:

- upstream continuable
- tidak ada critical blocker
- freshness `FRESH`
- warmup `READY`
- fallback `NO_FALLBACK` atau `LEGAL_PRIMARY_SUBSTITUTE`
- edge validation available
- edge status legal
- `win_probability >= 0.67`

### WARN

Diberikan bila:

- upstream continuable
- tidak ada critical blocker
- probability/legality masih cukup
- dan ada salah satu:
  - freshness `STALE_PRESERVED`
  - warmup `PARTIAL`
  - fallback `LEGAL_EMERGENCY_PRESERVE`
  - `0.55 <= win_probability < 0.67`
  - edge status degraded
  - validation partial
  - sample count rendah tapi belum invalid

### FAIL

Diberikan bila:

- ada critical blocker
- `win_probability < 0.55`
- edge validation unavailable
- edge status invalid
- illegal fallback
- warmup insufficient
- freshness no producer / governance hard fail

## Output Contract

```json
{
  "layer": "L7",
  "layer_version": "1.0.0",
  "timestamp": "ISO-8601",
  "input_ref": "string",
  "status": "PASS|WARN|FAIL",
  "continuation_allowed": true,
  "blocker_codes": [],
  "warning_codes": [],
  "fallback_class": "NO_FALLBACK|LEGAL_PRIMARY_SUBSTITUTE|LEGAL_EMERGENCY_PRESERVE|ILLEGAL_FALLBACK",
  "freshness_state": "FRESH|STALE_PRESERVED|DEGRADED|NO_PRODUCER",
  "warmup_state": "READY|PARTIAL|INSUFFICIENT",
  "coherence_band": "HIGH|MID|LOW",
  "score_numeric": 0.0,
  "features": {
    "feature_vector": {},
    "feature_hash": "string"
  },
  "routing": {
    "source_used": [],
    "fallback_used": false,
    "next_legal_targets": ["L8"]
  },
  "audit": {
    "rule_hits": [],
    "blocker_triggered": false,
    "notes": []
  }
}
```
