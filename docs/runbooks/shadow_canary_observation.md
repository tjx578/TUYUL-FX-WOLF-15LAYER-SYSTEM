# Shadow Canary Observation Runbook

## Tujuan

Memvalidasi bukti canary yang benar dari engine runtime tanpa menyentuh execution authority atau mengubah verdict path.

## Scope

- Engine service only
- Read-only observation
- Tidak mengubah execution, AuthorizedOrderIntent, atau L12 authority

## Preconditions

- Redis dan ingest sudah sehat atau membaik
- Contract tests tetap hijau
- Railway Engine service adalah service yang benar-benar menjalankan pipeline analisis

## Step 1 — Enable Shadow Capture

Pasang env di Railway Engine service:

```env
WOLF_SHADOW_CAPTURE_ENABLED=1
WOLF_SHADOW_JOURNAL_PATH=/tmp/wolf_shadow_capture.jsonl
```

Jika path ephemeral sulit diambil, gunakan volume:

```env
WOLF_SHADOW_JOURNAL_PATH=/data/wolf_shadow_capture.jsonl
```

Redeploy engine setelah env ditambahkan.

## Step 2 — Verify Journal Exists

Pastikan file journal benar-benar tertulis di engine runtime.

Checklist:

1. Env dipasang di service engine, bukan Redis, ingest, atau execution.
2. Service sudah redeploy setelah env berubah.
3. Path journal writable.
4. Hook shadow capture aktif pada runtime path yang sedang berjalan.

Jika file tidak muncul, cek engine logs untuk keyword berikut:

```text
shadow
shadow_capture
WOLF_SHADOW_CAPTURE_ENABLED
decision_bundle
projection
```

## Step 3 — Observation Window

Biarkan engine berjalan cukup lama untuk menghasilkan sampel bermakna.

- Minimum: beberapa jam
- Ideal: 24–72 jam

## Step 4 — Run Analyzer

Jalankan analyzer pada host atau container yang dapat mengakses file journal:

```bash
python scripts/analyze_shadow_journal.py --path /tmp/wolf_shadow_capture.jsonl --json
```

atau:

```bash
python scripts/analyze_shadow_journal.py --path /data/wolf_shadow_capture.jsonl --json
```

## Step 5 — Interpret Exit Code

- `0`: analisis selesai, lanjut evaluasi hasil
- `1`: file missing/unreadable, audit env placement dan writable path
- `2`: integrity violation, halt escalation

## Step 6 — Canary Gates

Target hasil minimum:

```text
exit_code = 0
v11_leaks = 0
projection_failures = 0 atau known-benign only
signal_id_mismatches = 0
foreign_signal_id = 0
legacy verdict unchanged
```

Jika analyzer memberi exit code `2`, jangan lanjut P1-D.

## Step 7 — Engine Log Audit

Cek engine logs selama window yang sama untuk pola berikut:

```text
DATA QUALITY degraded
stale_preserved
D1
Phase 1 DEGRADED
L2 FAIL
L3 FAIL
L7 FAIL
L8 FAIL
L9 FAIL
could not convert string to float: 'LOW'
shadow_capture
projection_failure
DecisionBundle
```

## Decision Table

- Analyzer clean: lanjut ke capture expansion dan dashboard shadow metrics; P1-D tetap sesudah itu.
- Analyzer violation: halt P1-D, lakukan forensic audit pada hook placement, adapter mapping, dan signal lifecycle.
- Journal missing: audit env placement, writable path, service selection, dan runtime hook call-site.

## Non-Negotiables

- Jangan gunakan Redis log sebagai bukti shadow canary.
- Jangan ubah execution authority saat observasi.
- Jangan lanjut AuthorizedOrderIntent enforcement sebelum canary clean.
