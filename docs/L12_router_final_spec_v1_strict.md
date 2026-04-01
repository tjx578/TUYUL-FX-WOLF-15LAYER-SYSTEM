# L12 Router Final Spec v1 — Strict Constitutional Mode

## Tujuan

L12 adalah **constitutional verdict authority** untuk Phase 5.
L12 menerima hasil legal dari fase-fase sebelumnya dan menjadi **satu-satunya authority**
yang boleh mengeluarkan verdict operasional tingkat sistem:

- `EXECUTE`
- `HOLD`
- `NO_TRADE`

L12 **bukan**:

- eksekutor live
- sizing engine
- enrichment engine
- pengganti firewall atau governance layer lain

## Authority Boundary

L12 boleh mengeluarkan:

- `verdict`
- `verdict_status`
- `continuation_allowed`
- `next_legal_targets`
- `gate_summary`
- `blocker_codes`
- `warning_codes`
- `audit trail`

L12 tidak boleh:

- mengirim order live
- mengarang lot final jika sizing authority final tidak tersedia
- membypass veto dari phase-phase sebelumnya

## Input Authority

L12 hanya boleh menilai verdict jika:

- upstream wrapper sampai **Phase 4** `continuation_allowed = true`
- `next_legal_targets` mengandung `PHASE_5`
- hasil phase 1, 2, 3, dan 4 tersedia
- tidak ada fatal halt sebelum L12

## Canonical Score

Field numerik utama L12 adalah:

`score_numeric := synthesis_score`

Makna:

- representasi mutu confluence constitutional
- bukan jaminan hasil
- bukan pengganti gate keras
- dipakai sebagai komponen synthesis, bukan satu-satunya penentu

## Gate Model

L12 memakai ringkasan gate konstitusional. Versi v1 memakai 9 gate konseptual:

1. FOUNDATION_OK
2. SCORING_OK
3. ENRICHMENT_OK
4. STRUCTURE_OK
5. RISK_CHAIN_OK
6. INTEGRITY_OK
7. PROBABILITY_OK
8. FIREWALL_OK
9. GOVERNANCE_OK

### Interpretasi

- gate bisa `PASS | WARN | FAIL`
- satu `FAIL` pada gate keras => minimal `NO_TRADE`
- semua gate minimal `PASS/WARN` => lanjut ke synthesis verdict

## Verdict Rules

### EXECUTE

Hanya bila:

- upstream continuable
- tidak ada hard blocker
- tidak ada critical gate `FAIL`
- synthesis_score tinggi
- risk chain legal
- structure legal
- firewall legal
- governance legal

### HOLD

Bila:

- upstream continuable
- tidak ada hard blocker fatal
- ada warning / kualitas sedang / confluence belum ideal
- tapi sistem belum masuk area `NO_TRADE`

### NO_TRADE

Bila:

- upstream tidak continuable
- ada hard blocker
- ada critical gate `FAIL`
- synthesis_score terlalu rendah
- verdict authority tidak punya dasar legal untuk EXECUTE atau HOLD

## Threshold v1

| Parameter | Value | Keterangan |
| --- | --- | --- |
| EXECUTE_MIN_SCORE | 0.65 | Minimum synthesis score untuk EXECUTE |
| HOLD_MIN_SCORE | 0.40 | Minimum synthesis score untuk HOLD |

## Hard Gates

Gate yang FAIL-nya langsung memaksa NO_TRADE:

- FOUNDATION_OK
- STRUCTURE_OK
- RISK_CHAIN_OK
- FIREWALL_OK

## Non-fatal Gates

- ENRICHMENT_OK: FAIL hanya menambah warning, tidak memblokir
- SCORING_OK: FAIL memblokir (via blocker code), bukan hard gate langsung
- INTEGRITY_OK: FAIL memblokir
- PROBABILITY_OK: FAIL memblokir
- GOVERNANCE_OK: FAIL memblokir

## Output Contract

```json
{
  "layer": "L12",
  "layer_version": "1.0.0",
  "timestamp": "ISO-8601",
  "input_ref": "string",
  "verdict": "EXECUTE|HOLD|NO_TRADE",
  "verdict_status": "PASS|WARN|FAIL",
  "continuation_allowed": true,
  "next_legal_targets": ["PHASE_6"],
  "score_numeric": 0.0,
  "gate_summary": {
    "FOUNDATION_OK": "PASS",
    "SCORING_OK": "PASS",
    "ENRICHMENT_OK": "WARN",
    "STRUCTURE_OK": "PASS",
    "RISK_CHAIN_OK": "PASS",
    "INTEGRITY_OK": "PASS",
    "PROBABILITY_OK": "PASS",
    "FIREWALL_OK": "PASS",
    "GOVERNANCE_OK": "PASS"
  },
  "blocker_codes": [],
  "warning_codes": [],
  "audit": {
    "rule_hits": [],
    "blocker_triggered": false,
    "notes": []
  }
}
```

## Implementation Reference

- Router evaluator: `constitution/l12_router_evaluator.py`
- Phase 5 adapter: `constitution/phase5_constitutional_verdict_adapter.py`
- E2E wrapper: `constitution/end_to_end_constitutional_wrapper_to_phase5.py`
- Final export: `constitution/final_normalized_payload_exporter.py`
