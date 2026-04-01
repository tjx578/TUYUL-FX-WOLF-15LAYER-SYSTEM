# L6 Router Final Spec v1 — Strict Constitutional Mode

## Tujuan

L6 adalah **capital firewall / correlation-risk legality governor** untuk Phase 4.  
L6 menerima propagasi legal dari **L11** dan menilai apakah kondisi modal, drawdown,
correlation exposure, dan firewall risk masih cukup layak untuk diteruskan ke **L10**.

L6 **bukan**:

- decision engine
- execution authority
- sizing module
- final verdict router

## Authority Boundary

L6 hanya boleh mengeluarkan:

- status legality: `PASS | WARN | FAIL`
- continuation legality ke `L10`
- score band / score numeric
- blocker / warning codes
- audit trail
- feature envelope untuk replay / backtest / pattern mining

L6 tidak boleh mengeluarkan:

- `execute`
- `trade_valid`
- `position_size`
- `final_verdict`

## Canonical Score

Field numerik utama L6 adalah:

`score_numeric := firewall_score`

Makna:

- representasi mutu capital firewall / risk legality
- bukan izin trade final
- bukan sizing authority
- dipakai hanya untuk legality envelope L6

## Coherence Band untuk L6

Field band tetap memakai nama `coherence_band`, tetapi di L6 maknanya adalah **firewall band**.

Threshold baseline:

- `HIGH >= 0.85`
- `MID >= 0.70 and < 0.85`
- `LOW < 0.70`

## Critical Blockers

Hard fail L6:

- `UPSTREAM_L11_NOT_CONTINUABLE`
- `REQUIRED_RISK_SOURCE_MISSING`
- `ACCOUNT_STATE_UNAVAILABLE`
- `DRAWDOWN_LIMIT_BREACHED`
- `DAILY_LOSS_LIMIT_BREACHED`
- `CORRELATION_EXPOSURE_EXCEEDED`
- `VOL_CLUSTER_EXTREME`
- `FIREWALL_STATE_INVALID`
- `FIREWALL_SCORE_BELOW_MINIMUM`
- `FRESHNESS_GOVERNANCE_HARD_FAIL`
- `WARMUP_INSUFFICIENT`
- `FALLBACK_DECLARED_BUT_NOT_ALLOWED`
- `CONTRACT_PAYLOAD_MALFORMED`

## Warning Envelope

Non-fatal degradation yang boleh menghasilkan `WARN`:

- `STALE_PRESERVED`
- `PARTIAL` warmup
- legal emergency fallback
- firewall band `MID`
- drawdown elevated but not breached
- daily loss elevated but not breached
- correlation exposure elevated but below hard cap
- volatility cluster high
- firewall state degraded

## Compression Rules

### PASS

Diberikan bila:

- upstream L11 continuable
- tidak ada critical blocker
- freshness `FRESH`
- warmup `READY`
- fallback `NO_FALLBACK` atau `LEGAL_PRIMARY_SUBSTITUTE`
- account state available
- firewall state legal
- drawdown/daily loss/correlation exposure tidak breach
- `firewall_score >= 0.85`

### WARN

Diberikan bila:

- upstream L11 continuable
- tidak ada critical blocker
- firewall envelope masih legal
- dan ada salah satu:
  - freshness `STALE_PRESERVED`
  - warmup `PARTIAL`
  - fallback `LEGAL_EMERGENCY_PRESERVE`
  - `0.70 <= firewall_score < 0.85`
  - drawdown elevated
  - daily loss elevated
  - correlation exposure elevated
  - volatility cluster high
  - firewall state degraded

### FAIL

Diberikan bila:

- ada critical blocker
- `firewall_score < 0.70`
- account state unavailable
- drawdown/daily loss hard breach
- correlation exposure hard breach
- volatility cluster extreme
- firewall state invalid
- illegal fallback
- warmup insufficient
- freshness no producer / governance hard fail
