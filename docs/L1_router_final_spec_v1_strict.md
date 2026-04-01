# L1 Router Final Spec v1 (Strict Constitutional Mode)

Status: Proposed Final v1  
Scope: L1 only  
Role: Context governor, not verdict authority

## 1. Design intent

Dokumen ini membekukan versi L1 yang lebih ketat agar siap dipakai untuk:

- implementasi runtime
- backtest / replay
- audit trail
- pattern mining lintas layer

L1 hanya berwenang menilai:

- legalitas data/context
- legalitas propagasi ke L2
- kualitas coherence context

L1 tidak berwenang mengeluarkan:

- direction
- entry / stop / target
- trade_valid
- execute / no_trade verdict

Authority final tetap berada di L12.

---

## 2. Constitutional invariants

```yaml
l1_invariants:
  - L1 is a context governor only.
  - L1 must never emit execution authority.
  - Hard legality checks must run before coherence scoring.
  - status == FAIL implies continuation_allowed == false.
  - continuation_allowed == true implies next_legal_targets == ["L2"].
  - LOW coherence can never override a hard blocker.
  - Fallback legality can cap status but cannot upgrade a failed legality check.
```

---

## 3. Evaluation order (frozen)

```yaml
l1_evaluation_order:
  1: check_contract_integrity
  2: check_data_availability_gate
  3: check_freshness_warmup_gate
  4: check_fallback_legality_gate
  5: compute_context_coherence
  6: derive_coherence_band
  7: compress_status
  8: set_continuation_legality
  9: emit_contract
```

Interpretasi:

- langkah 1–4 = legality domain
- langkah 5–6 = scoring domain
- langkah 7–9 = compression/output domain

---

## 4. L1 sub-gates

### 4.1 L1-A Data Availability Gate

Memastikan producer/snapshot/dependency minimum memang ada dan valid.

Output:

- PASS
- FAIL

### 4.2 L1-B Freshness/Warmup Gate

Memastikan data bukan cuma ada, tapi juga layak dipakai secara epistemik.

Output:

- PASS
- WARN
- FAIL

### 4.3 L1-C Context Coherence Gate

Mengukur kualitas sinkronisasi context antar source.

Output:

- HIGH
- MID
- LOW

### 4.4 L1-D Continuation Legality Gate

Mengubah hasil sub-gate menjadi status final:

- PASS
- WARN
- FAIL

---

## 5. Critical blockers spec (frozen v1)

```yaml
l1_critical_blockers:
  - code: CONTRACT_PAYLOAD_MALFORMED
    description: Required contract fields are missing, malformed, or type-invalid.
    severity: HARD_FAIL
    continuation_allowed: false

  - code: REQUIRED_PRODUCER_MISSING
    description: Required producer/source for legal L1 context is unavailable.
    severity: HARD_FAIL
    continuation_allowed: false

  - code: FRESHNESS_GOVERNANCE_HARD_FAIL
    description: Freshness governance marks runtime epistemically unsafe.
    severity: HARD_FAIL
    continuation_allowed: false

  - code: WARMUP_INSUFFICIENT
    description: Warmup completeness is below legal minimum for propagation.
    severity: HARD_FAIL
    continuation_allowed: false

  - code: SNAPSHOT_INVALID_OR_CORRUPT
    description: Current or preserved snapshot is corrupt, incomplete, or structurally invalid.
    severity: HARD_FAIL
    continuation_allowed: false

  - code: SESSION_STATE_INVALID
    description: Session state required by L1 is contradictory, invalid, or untrusted.
    severity: HARD_FAIL
    continuation_allowed: false

  - code: REGIME_SERVICE_UNAVAILABLE_NO_LEGAL_FALLBACK
    description: Regime source is unavailable and no constitutionally valid fallback exists.
    severity: HARD_FAIL
    continuation_allowed: false

  - code: FALLBACK_DECLARED_BUT_NOT_ALLOWED
    description: Fallback path was invoked but is not approved by governance.
    severity: HARD_FAIL
    continuation_allowed: false
```

Rule:

- bila satu saja blocker aktif, `status = FAIL`
- bila blocker aktif, `continuation_allowed = false`
- blocker list wajib diserialisasi ke `blocker_codes`

---

## 6. Fallback legality matrix (frozen v1)

```yaml
fallback_classes:
  NO_FALLBACK:
    description: No fallback path used or available.
    max_status: CONDITIONAL
    blocker: conditional

  LEGAL_PRIMARY_SUBSTITUTE:
    description: Approved substitute with equivalent legal standing to the primary source.
    max_status: PASS
    blocker: false

  LEGAL_EMERGENCY_PRESERVE:
    description: Preserved snapshot fallback allowed only for continuity under degraded conditions.
    max_status: WARN
    blocker: false

  ILLEGAL_FALLBACK:
    description: Fallback exists or was invoked but is not constitutionally approved.
    max_status: FAIL
    blocker: true
```

### Fallback rules (frozen)

```yaml
fallback_rules:
  - if: fallback_class == ILLEGAL_FALLBACK
    result: FAIL
    reason: fallback_illegal

  - if: fallback_class == LEGAL_EMERGENCY_PRESERVE
    result_cap: WARN
    reason: preserved_context_cannot_upgrade_to_pass

  - if: fallback_class == LEGAL_PRIMARY_SUBSTITUTE
    result_cap: PASS
    reason: equivalent_source_allowed

  - if: fallback_class == NO_FALLBACK and required_producer_missing == true
    result: FAIL
    reason: no_legal_recovery_path

  - if: fallback_class == NO_FALLBACK and required_producer_missing == false
    result: CONDITIONAL
    reason: no_fallback_used
```

Interpretasi penting:

- `LEGAL_EMERGENCY_PRESERVE` tidak pernah boleh menghasilkan PASS
- `ILLEGAL_FALLBACK` selalu hard fail
- `NO_FALLBACK` bukan status baik/buruk dengan sendirinya; ia legal hanya jika producer wajib tidak hilang

---

## 7. Freshness and warmup states

```yaml
freshness_state_enum:
  - FRESH
  - STALE_PRESERVED
  - DEGRADED
  - NO_PRODUCER

warmup_state_enum:
  - READY
  - PARTIAL
  - INSUFFICIENT
```

### Freshness legality

```yaml
freshness_rules:
  - if: freshness_state == NO_PRODUCER
    result: FAIL

  - if: freshness_state == STALE_PRESERVED
    result_cap: WARN

  - if: freshness_state == DEGRADED
    result_cap: WARN
```

### Warmup legality

```yaml
warmup_rules:
  - if: warmup_state == INSUFFICIENT
    result: FAIL

  - if: warmup_state == PARTIAL
    result_cap: WARN
```

Catatan:

- `DEGRADED` bukan auto-fail, tetapi hanya boleh bertahan dalam envelope sempit
- `PARTIAL` tidak boleh naik ke PASS kecuali desain diubah pada versi berikutnya

---

## 8. Context coherence thresholds (frozen baseline v1)

```yaml
coherence_thresholds:
  HIGH:
    gte: 0.85
  MID:
    gte: 0.65
    lt: 0.85
  LOW:
    lt: 0.65
```

Interpretasi:

- threshold ini baseline awal
- boleh dikalibrasi di versi berikutnya berdasarkan distribusi data nyata
- selama v1, threshold ini dianggap fixed untuk konsistensi replay/backtest

### Coherence rules

```yaml
coherence_rules:
  - if: coherence_band == LOW
    result: FAIL

  - if: coherence_band == MID
    result_cap: PASS_OR_WARN

  - if: coherence_band == HIGH
    result_cap: PASS_OR_WARN
```

---

## 9. Final compression logic (strict mode)

```yaml
compression_logic:
  - if: any_critical_blocker == true
    final_status: FAIL

  - if: freshness_state == NO_PRODUCER
    final_status: FAIL

  - if: warmup_state == INSUFFICIENT
    final_status: FAIL

  - if: coherence_band == LOW
    final_status: FAIL

  - if: fallback_class == ILLEGAL_FALLBACK
    final_status: FAIL

  - if:
      freshness_state == FRESH
      and warmup_state == READY
      and coherence_band in [HIGH, MID]
      and fallback_class in [NO_FALLBACK, LEGAL_PRIMARY_SUBSTITUTE]
      and any_critical_blocker == false
    final_status: PASS

  - if:
      freshness_state in [STALE_PRESERVED, DEGRADED, FRESH]
      and warmup_state in [READY, PARTIAL]
      and coherence_band in [HIGH, MID]
      and fallback_class in [NO_FALLBACK, LEGAL_PRIMARY_SUBSTITUTE, LEGAL_EMERGENCY_PRESERVE]
      and any_critical_blocker == false
    final_status: WARN

  - else:
      final_status: FAIL
```

### Practical meaning

- PASS hanya untuk envelope paling bersih
- WARN untuk envelope legal tapi terdegradasi
- FAIL untuk semua kasus di luar envelope legal

---

## 10. Continuation legality

```yaml
continuation_rules:
  - if: final_status == FAIL
    continuation_allowed: false
    next_legal_targets: []

  - if: final_status in [PASS, WARN]
    continuation_allowed: true
    next_legal_targets: ["L2"]
```

---

## 11. Canonical L1 output contract (final v1)

```yaml
l1_output_contract:
  layer: "L1"
  layer_version: "1.0.0"
  timestamp: "ISO8601"
  input_ref: "string"
  status: "PASS|WARN|FAIL"
  continuation_allowed: "boolean"
  blocker_codes: ["string"]
  warning_codes: ["string"]
  fallback_class: "NO_FALLBACK|LEGAL_PRIMARY_SUBSTITUTE|LEGAL_EMERGENCY_PRESERVE|ILLEGAL_FALLBACK"
  freshness_state: "FRESH|STALE_PRESERVED|DEGRADED|NO_PRODUCER"
  warmup_state: "READY|PARTIAL|INSUFFICIENT"
  coherence_score: "float"
  coherence_band: "HIGH|MID|LOW"
  features:
    market_regime: "string"
    dominant_force: "string"
    context_sources_used: ["string"]
    feature_vector: "object"
    feature_hash: "string"
  routing:
    source_used: ["string"]
    fallback_used: "boolean"
    next_legal_targets: ["string"]
  audit:
    rule_hits: ["string"]
    blocker_triggered: "boolean"
    notes: ["string"]
```

### Naming changes from draft

Perubahan yang diketatkan dari draft awal:

- `confidence_band` diganti menjadi `coherence_band`
- `score_numeric` diganti menjadi `coherence_score`
- `source_used` dipertahankan, tetapi `context_sources_used` juga diletakkan di features untuk audit source fusion

Alasan:

- menghindari ambiguitas makna
- menjaga field tetap spesifik terhadap peran L1

---

## 12. Example output (legal degraded case)

```json
{
  "layer": "L1",
  "layer_version": "1.0.0",
  "timestamp": "2026-03-28T10:15:00+07:00",
  "input_ref": "EURUSD_H1_run_00041",
  "status": "WARN",
  "continuation_allowed": true,
  "blocker_codes": [],
  "warning_codes": ["STALE_PRESERVED_CONTEXT", "PARTIAL_WARMUP"],
  "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
  "freshness_state": "STALE_PRESERVED",
  "warmup_state": "PARTIAL",
  "coherence_score": 0.74,
  "coherence_band": "MID",
  "features": {
    "market_regime": "TRENDING",
    "dominant_force": "MOMENTUM",
    "context_sources_used": ["regime_service", "preserved_snapshot"],
    "feature_vector": {
      "context_coherence": 0.74,
      "session_state": "LONDON_OPEN"
    },
    "feature_hash": "L1_TRENDING_MOMENTUM_WARN_74"
  },
  "routing": {
    "source_used": ["regime_service", "preserved_snapshot"],
    "fallback_used": true,
    "next_legal_targets": ["L2"]
  },
  "audit": {
    "rule_hits": [
      "fallback_class=LEGAL_EMERGENCY_PRESERVE",
      "warmup_state=PARTIAL",
      "coherence_band=MID"
    ],
    "blocker_triggered": false,
    "notes": ["Context legally degraded but still propagable."]
  }
}
```

---

## 13. Pseudocode reference

```python
def evaluate_l1_status(inp):
    blocker_codes = check_contract_and_blockers(inp)
    if blocker_codes:
        return fail_contract(inp, blocker_codes)

    freshness_state = eval_freshness(inp)
    warmup_state = eval_warmup(inp)
    fallback_class = eval_fallback(inp)

    if freshness_state == "NO_PRODUCER":
        return fail_contract(inp, ["REQUIRED_PRODUCER_MISSING"])

    if warmup_state == "INSUFFICIENT":
        return fail_contract(inp, ["WARMUP_INSUFFICIENT"])

    if fallback_class == "ILLEGAL_FALLBACK":
        return fail_contract(inp, ["FALLBACK_DECLARED_BUT_NOT_ALLOWED"])

    coherence_score = compute_context_coherence(inp)
    coherence_band = band_from_score(coherence_score)

    if coherence_band == "LOW":
        return fail_contract(inp, ["LOW_CONTEXT_COHERENCE"])

    clean_pass = (
        freshness_state == "FRESH"
        and warmup_state == "READY"
        and coherence_band in {"HIGH", "MID"}
        and fallback_class in {"NO_FALLBACK", "LEGAL_PRIMARY_SUBSTITUTE"}
    )

    if clean_pass:
        return pass_contract(inp, coherence_score, coherence_band, freshness_state, warmup_state, fallback_class)

    return warn_contract(inp, coherence_score, coherence_band, freshness_state, warmup_state, fallback_class)
```

---

## 14. Freeze decisions for v1

```yaml
v1_freeze:
  critical_blockers_spec: frozen
  fallback_legality_matrix: frozen
  evaluation_order: frozen
  coherence_thresholds: frozen_baseline
  l1_output_contract: frozen
  authority_boundary: frozen
```

---

## 15. Implementation notes

- Gunakan enum/constant, bukan string literal tersebar
- Semua blocker dan warning harus punya code resmi
- Semua decision path harus menulis `rule_hits`
- Jangan hitung `coherence_score` bila contract/blocker sudah fail fatal, kecuali mode debug eksplisit
- Backtest/replay wajib membaca contract output, bukan feature hash
