# L9 Router Final Spec v1 — Strict Constitutional Mode

## Tujuan

L9 adalah **structure / entry-timing legality governor** untuk Phase 3.  
L9 menerima propagasi legal dari **L8** dan menilai apakah structure alignment,
liquidity timing, dan entry envelope masih cukup layak untuk diteruskan ke fase berikutnya.

L9 **bukan**:

- decision engine
- execution authority
- sizing module
- final verdict router

## Authority Boundary

L9 hanya boleh mengeluarkan:

- status legality: `PASS | WARN | FAIL`
- continuation legality ke fase berikutnya
- score band / score numeric
- blocker / warning codes
- audit trail
- feature envelope untuk replay / backtest / pattern mining

L9 tidak boleh mengeluarkan:

- `direction`
- `execute`
- `trade_valid`
- `position_size`
- `final_verdict`

## Canonical Score

Field numerik utama L9 adalah:

`score_numeric := structure_score`

Makna:

- representasi mutu structure / timing legality
- bukan sinyal entry final
- bukan izin trade
- dipakai hanya untuk legality envelope L9

## Coherence Band untuk L9

Field band tetap memakai nama `coherence_band`, tetapi di L9 maknanya adalah **structure band**.

Threshold baseline:

- `HIGH >= 0.80`
- `MID >= 0.65 and < 0.80`
- `LOW < 0.65`

## Critical Blockers

Hard fail L9:

- `UPSTREAM_L8_NOT_CONTINUABLE`
- `REQUIRED_STRUCTURE_SOURCE_MISSING`
- `STRUCTURE_ALIGNMENT_INVALID`
- `ENTRY_TIMING_UNAVAILABLE`
- `LIQUIDITY_STATE_INVALID`
- `STRUCTURE_SCORE_BELOW_MINIMUM`
- `FRESHNESS_GOVERNANCE_HARD_FAIL`
- `WARMUP_INSUFFICIENT`
- `FALLBACK_DECLARED_BUT_NOT_ALLOWED`
- `CONTRACT_PAYLOAD_MALFORMED`

## Warning Envelope

Non-fatal degradation yang boleh menghasilkan `WARN`:

- `STALE_PRESERVED`
- `PARTIAL` warmup
- legal emergency fallback
- structure band `MID`
- liquidity sweep/timing partial
- entry timing degraded
- structure stable tapi belum ideal

## Compression Rules

### PASS

Diberikan bila:

- upstream L8 continuable
- tidak ada critical blocker
- freshness `FRESH`
- warmup `READY`
- fallback `NO_FALLBACK` atau `LEGAL_PRIMARY_SUBSTITUTE`
- structure alignment legal
- entry timing available
- liquidity state legal
- `structure_score >= 0.80`

### WARN

Diberikan bila:

- upstream L8 continuable
- tidak ada critical blocker
- structure envelope masih legal
- dan ada salah satu:
  - freshness `STALE_PRESERVED`
  - warmup `PARTIAL`
  - fallback `LEGAL_EMERGENCY_PRESERVE`
  - `0.65 <= structure_score < 0.80`
  - entry timing degraded
  - liquidity partial
  - structure non-ideal

### FAIL

Diberikan bila:

- ada critical blocker
- `structure_score < 0.65`
- structure alignment invalid
- entry timing unavailable
- liquidity invalid
- illegal fallback
- warmup insufficient
- freshness no producer / governance hard fail
