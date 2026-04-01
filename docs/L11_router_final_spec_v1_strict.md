# L11 Router Final Spec v1 — Strict Constitutional Mode

## Tujuan

L11 adalah **risk-reward / battle-strategy legality governor** untuk Phase 4.  
L11 menerima propagasi legal dari **Phase 3 / upstream wrapper** dan menilai apakah
envelope risk-reward, ATR-based battle plan, dan target-stop geometry masih cukup
layak untuk diteruskan ke **L6**.

L11 **bukan**:

- decision engine
- execution authority
- sizing module
- final verdict router

## Authority Boundary

L11 hanya boleh mengeluarkan:

- status legality: `PASS | WARN | FAIL`
- continuation legality ke `L6`
- score band / score numeric
- blocker / warning codes
- audit trail
- feature envelope untuk replay / backtest / pattern mining

L11 tidak boleh mengeluarkan:

- `execute`
- `trade_valid`
- `position_size`
- `final_verdict`

## Canonical Score

Field numerik utama L11 adalah:

`score_numeric := rr_score`

Makna:

- representasi mutu risk-reward / battle-plan legality
- bukan izin trade final
- bukan sizing authority
- dipakai hanya untuk legality envelope L11

## Coherence Band untuk L11

Field band tetap memakai nama `coherence_band`, tetapi di L11 maknanya adalah **RR band**.

Threshold baseline:

- `HIGH >= 0.80`
- `MID >= 0.65 and < 0.80`
- `LOW < 0.65`

## Critical Blockers

Hard fail L11:

- `UPSTREAM_NOT_CONTINUABLE`
- `REQUIRED_RR_SOURCE_MISSING`
- `ENTRY_UNAVAILABLE`
- `STOP_LOSS_UNAVAILABLE`
- `TAKE_PROFIT_UNAVAILABLE`
- `RR_INVALID`
- `BATTLE_PLAN_UNAVAILABLE`
- `ATR_CONTEXT_UNAVAILABLE`
- `RR_SCORE_BELOW_MINIMUM`
- `FRESHNESS_GOVERNANCE_HARD_FAIL`
- `WARMUP_INSUFFICIENT`
- `FALLBACK_DECLARED_BUT_NOT_ALLOWED`
- `CONTRACT_PAYLOAD_MALFORMED`

## Warning Envelope

Non-fatal degradation yang boleh menghasilkan `WARN`:

- `STALE_PRESERVED`
- `PARTIAL` warmup
- legal emergency fallback
- RR band `MID`
- ATR context partial
- battle plan degraded
- target geometry non-ideal
- multi-target incomplete but still legal

## Compression Rules

### PASS

Diberikan bila:

- upstream continuable
- tidak ada critical blocker
- freshness `FRESH`
- warmup `READY`
- fallback `NO_FALLBACK` atau `LEGAL_PRIMARY_SUBSTITUTE`
- entry / stop / TP available
- RR legal
- battle plan available
- ATR context available
- `rr_score >= 0.80`

### WARN

Diberikan bila:

- upstream continuable
- tidak ada critical blocker
- RR envelope masih legal
- dan ada salah satu:
  - freshness `STALE_PRESERVED`
  - warmup `PARTIAL`
  - fallback `LEGAL_EMERGENCY_PRESERVE`
  - `0.65 <= rr_score < 0.80`
  - ATR context partial
  - battle plan degraded
  - target geometry non-ideal
  - multi-target incomplete

### FAIL

Diberikan bila:

- ada critical blocker
- `rr_score < 0.65`
- RR invalid
- entry/SL/TP unavailable
- battle plan unavailable
- ATR context unavailable
- illegal fallback
- warmup insufficient
- freshness no producer / governance hard fail
