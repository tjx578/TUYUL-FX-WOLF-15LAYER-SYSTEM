# Final Normalized Payload Schema v1 — Strict Constitutional Mode

## Tujuan

Schema ini menormalkan seluruh output pipeline sampai **Phase 5 / L12** ke satu envelope final
yang:

- mudah diekspor
- mudah diaudit
- mudah direplay
- stabil untuk integrasi Phase 6 governance, Phase 7 sovereignty, dan export layer

Schema ini **bukan** order ticket live dan **bukan** execution payload.

## Struktur Atas

```json
{
  "schema": "FINAL_NORMALIZED_PAYLOAD_V1",
  "schema_version": "1.0.0",
  "input_ref": "string",
  "timestamp": "ISO-8601",
  "pipeline": {
    "status": "PASS|WARN|FAIL",
    "final_verdict": "EXECUTE|HOLD|NO_TRADE",
    "final_verdict_status": "PASS|WARN|FAIL",
    "continuation_allowed": true,
    "next_legal_targets": ["PHASE_6"]
  },
  "phase_status": {
    "PHASE_1": "PASS|WARN|FAIL",
    "PHASE_2": "PASS|WARN|FAIL",
    "PHASE_2_5": "PASS|WARN",
    "PHASE_3": "PASS|WARN|FAIL",
    "PHASE_4": "PASS|WARN|FAIL",
    "PHASE_5": "PASS|WARN|FAIL"
  },
  "verdict": {
    "verdict": "EXECUTE|HOLD|NO_TRADE",
    "verdict_status": "PASS|WARN|FAIL",
    "synthesis_score": 0.0,
    "gate_summary": {}
  },
  "layer_status": {
    "L1": "PASS|WARN|FAIL",
    "L2": "PASS|WARN|FAIL",
    "L3": "PASS|WARN|FAIL",
    "L4": "PASS|WARN|FAIL",
    "L5": "PASS|WARN|FAIL",
    "L7": "PASS|WARN|FAIL",
    "L8": "PASS|WARN|FAIL",
    "L9": "PASS|WARN|FAIL",
    "L11": "PASS|WARN|FAIL",
    "L6": "PASS|WARN|FAIL",
    "L10": "PASS|WARN|FAIL",
    "L12": "PASS|WARN|FAIL"
  },
  "scores": {
    "L1": 0.0,
    "L2": 0.0,
    "L3": 0.0,
    "L4": 0.0,
    "L5": 0.0,
    "L7": 0.0,
    "L8": 0.0,
    "L9": 0.0,
    "L11": 0.0,
    "L6": 0.0,
    "L10": 0.0,
    "L12": 0.0
  },
  "blockers": [],
  "warnings": [],
  "trace": {},
  "audit": {}
}
```

## Prinsip Normalisasi

1. **Final verdict authority tetap L12**
2. Semua phase diringkas, tetapi trace detail tetap dipertahankan
3. Layer yang tidak ada di pipeline versi ini tidak dipaksa diisi angka fiktif
4. `blockers` dan `warnings` final adalah agregasi deduplicated
5. `trace` menyimpan objek result per wrapper penting untuk replay

## Mapping Utama

- `pipeline.final_verdict` <- `phase5_result.l12_result.verdict`
- `pipeline.final_verdict_status` <- `phase5_result.l12_result.verdict_status`
- `verdict.synthesis_score` <- `phase5_result.l12_result.score_numeric`
- `verdict.gate_summary` <- `phase5_result.l12_result.gate_summary`
- `phase_status.PHASE_1` <- `phase5_result.synthesis_payload.foundation_status`
- `phase_status.PHASE_2` <- `phase5_result.synthesis_payload.scoring_status`
- `phase_status.PHASE_2_5` <- `phase5_result.synthesis_payload.enrichment_status`
- `phase_status.PHASE_3` <- `phase5_result.synthesis_payload.structure_status`
- `phase_status.PHASE_4` <- `phase5_result.synthesis_payload.risk_chain_status`
- `phase_status.PHASE_5` <- `phase5_result.phase_status`

## Catatan Kepatuhan

- Payload final ini **analysis-only**
- Tidak boleh dipakai sebagai authority untuk live execution
- Jika downstream butuh export broker/order, itu harus dibuat di layer terpisah setelah governance/sovereignty yang sah

## Implementation Reference

- Exporter: `constitution/final_normalized_payload_exporter.py`
- Schema schema: `FINAL_NORMALIZED_PAYLOAD_V1`
- Schema version: `1.0.0`
