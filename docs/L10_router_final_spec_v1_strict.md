# L10 Router Final Spec v1 — Strict Constitutional Mode

## Tujuan

L10 adalah **position-sizing / risk-geometry legality governor** untuk Phase 4.  
L10 menerima propagasi legal dari **L6** dan menilai apakah geometry risiko, sizing input,
dan compliance envelope masih cukup layak untuk diteruskan ke fase berikutnya.

L10 **bukan**:

- decision engine
- execution authority
- final verdict router

## Authority Boundary

L10 hanya boleh mengeluarkan:

- status legality: `PASS | WARN | FAIL`
- continuation legality ke fase berikutnya
- score band / score numeric
- blocker / warning codes
- audit trail
- feature envelope untuk replay / backtest / pattern mining

L10 tidak boleh mengeluarkan:

- `execute`
- `trade_valid`
- `final_verdict`

Catatan penting:

- Jika arsitektur runtime belum punya account-state/sizing authority final, L10 hanya boleh
  menilai **legality geometry dan kelengkapan sizing input**, bukan mengarang lot final.

## Canonical Score

Field numerik utama L10 adalah:

`score_numeric := sizing_score`

Makna:

- representasi mutu legality geometry risiko / sizing envelope
- bukan izin trade final
- bukan jaminan sizing executable
- dipakai hanya untuk legality envelope L10

## Coherence Band untuk L10

Field band tetap memakai nama `coherence_band`, tetapi di L10 maknanya adalah **sizing band**.

Threshold baseline:

- `HIGH >= 0.85`
- `MID >= 0.70 and < 0.85`
- `LOW < 0.70`

## Critical Blockers

Hard fail L10:

- `UPSTREAM_L6_NOT_CONTINUABLE`
- `REQUIRED_SIZING_SOURCE_MISSING`
- `ENTRY_UNAVAILABLE`
- `STOP_LOSS_UNAVAILABLE`
- `RISK_INPUT_UNAVAILABLE`
- `GEOMETRY_INVALID`
- `POSITION_SIZING_UNAVAILABLE`
- `COMPLIANCE_INVALID`
- `SIZING_SCORE_BELOW_MINIMUM`
- `FRESHNESS_GOVERNANCE_HARD_FAIL`
- `WARMUP_INSUFFICIENT`
- `FALLBACK_DECLARED_BUT_NOT_ALLOWED`
- `CONTRACT_PAYLOAD_MALFORMED`

## Warning Envelope

Non-fatal degradation yang boleh menghasilkan `WARN`:

- `STALE_PRESERVED`
- `PARTIAL` warmup
- legal emergency fallback
- sizing band `MID`
- geometry non-ideal
- compliance degraded but legal
- sizing partial
- account-limit proximity elevated

## Compression Rules

### PASS

Diberikan bila:

- upstream L6 continuable
- tidak ada critical blocker
- freshness `FRESH`
- warmup `READY`
- fallback `NO_FALLBACK` atau `LEGAL_PRIMARY_SUBSTITUTE`
- entry/SL tersedia
- risk input tersedia
- geometry valid
- sizing available
- compliance legal
- `sizing_score >= 0.85`

### WARN

Diberikan bila:

- upstream L6 continuable
- tidak ada critical blocker
- sizing envelope masih legal
- dan ada salah satu:
  - freshness `STALE_PRESERVED`
  - warmup `PARTIAL`
  - fallback `LEGAL_EMERGENCY_PRESERVE`
  - `0.70 <= sizing_score < 0.85`
  - geometry non-ideal
  - compliance degraded
  - sizing partial
  - account-limit proximity elevated

### FAIL

Diberikan bila:

- ada critical blocker
- `sizing_score < 0.70`
- geometry invalid
- sizing unavailable
- compliance invalid
- risk input unavailable
- illegal fallback
- warmup insufficient
- freshness no producer / governance hard fail
