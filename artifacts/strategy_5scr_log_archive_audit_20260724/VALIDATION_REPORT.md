# Strategy 5S-CR — audit seluruh arsip log dan kesiapan tradeplan

## Verdict

Workflow awal strategi bekerja pada data log: seluruh 262 ekspor `logs.*` telah
dipindai, dinormalisasi, di-deduplicate, dikelompokkan menjadi lifecycle, dan
diproses dengan gate pressure radar yang sama dengan runtime. Hasilnya adalah
15 lifecycle canonical `ANALYSIS_READY` pada 13 pair.

Tradeplan dan presisi belum dapat diuji secara sah. Pada cutoff keputusan
masing-masing lifecycle, tabel Railway `canonical_candles` tidak memiliki satu
pun candle H1 atau H4 authoritative. Karena H1 closed confirmation dan H4
structural target adalah hard requirement, jumlah tradeplan yang eligible
adalah 0. Ini bukan berarti precision 0%; precision belum dapat dihitung karena
denominator-nya 0.

## Cakupan arsip

| Ukuran | Hasil |
|---|---:|
| File log diperiksa | 262 |
| Ukuran arsip | 849.232.475 byte |
| File dengan pressure marker | 11 |
| Byte-identical duplicate files | 12 |
| Pressure occurrences setelah byte-file dedup | 3.682 |
| Unique pressure events (SHA-256) | 1.985 |
| Overlap duplicate occurrences | 1.697 (46,09%) |
| Normalization errors | 0 |
| Symbol pada pressure events | 30 |
| Raw replay lifecycles | 556 |

Periode pressure event yang ditemukan adalah 9–23 Juli 2026 UTC. Overlap
duplicate yang tinggi berasal dari Railway export dengan rentang waktu yang
saling tumpang tindih; occurrence tersebut tidak boleh diperlakukan sebagai
event strategi baru.

## Hasil pressure radar

| Status manifest | Jumlah |
|---|---:|
| `ANALYSIS_READY` | 15 |
| `EXPIRED` | 27 |
| `WAITING_CANONICAL_LINEAGE` | 8 |

Pair `ANALYSIS_READY`: AUDCHF (2 lifecycle), AUDJPY, AUDUSD, CADJPY, CHFJPY,
EURAUD, EURGBP, GBPJPY, GBPNZD (2 lifecycle), NZDCHF, NZDJPY, NZDUSD, dan
USDCHF.

Status ini hanya berarti pair/lifecycle lolos workflow awal pemilihan pressure.
Status tersebut bukan rekomendasi BUY/SELL dan belum merupakan tradeplan.

## Coverage candle Railway

Coverage dievaluasi pada 15 lifecycle menggunakan hanya candle:

1. `complete=true`;
2. timestamp semantics bukan `UNSPECIFIED`;
3. `close_time <= decision_at_utc` untuk evidence;
4. M1 setelah keputusan hanya untuk outcome, terpisah dari evidence.

| Coverage | Hasil |
|---|---:|
| Lifecycle dengan evidence D1+H4+H1+M15+M1 lengkap | 0/15 |
| H4 closed bars sebelum keputusan | 0 untuk seluruh lifecycle |
| H1 closed bars sebelum keputusan | 0 untuk seluruh lifecycle |
| Lifecycle dengan sebagian M1 outcome bars | 3/15 |
| Tradeplan dapat dievaluasi | 0 |
| Outcome dapat diklasifikasi | 0 |
| Precision denominator | 0 |

M1 outcome yang tersedia pada sebagian lifecycle tidak boleh dipakai untuk
mengisi bukti H1/H4 yang hilang, dan tidak boleh dibaca sebelum tradeplan
dibekukan. Melakukannya akan menciptakan future-candle leakage.

## Implikasi untuk demo EA

Order path harus tetap tidak aktif. Hambatan saat ini bukan logika
pressure-to-tradeplan, melainkan dataset market evidence yang belum lengkap
pada grain dan cutoff yang diwajibkan sistem.

Langkah berikut yang paling tepat adalah mengekspor history dari broker MT5
untuk 13 pair tersebut pada D1, H4, H1, M15, dan M1. Gunakan rentang
1 Juni–24 Juli 2026, sertakan timezone broker, lalu normalisasi ke UTC dan
`CanonicalCandle`. Setelah itu jalankan:

1. evidence as-of tanpa candle masa depan;
2. builder tradeplan non-executable;
3. outcome M1 maksimum 240 bar setelah keputusan;
4. laporan TP1-first, SL-first, ambiguous-same-candle, timeout, no-data;
5. precision hanya dari tradeplan eligible dengan outcome terminal yang tidak
   ambigu.

## Reproduksi

```powershell
python -m scripts.audit_strategy_5scr_log_archive `
  C:\Users\INTEL\Downloads `
  --output-dir artifacts\strategy_5scr_log_archive_audit_20260724
```

Artefak sumber: `summary.json`, `source_manifest.csv`,
`unique_pressure_events.csv`, `lifecycles.csv`, `radar_manifests.csv`,
`canonical_radar_payloads.jsonl`, dan
`railway_candle_coverage_summary.json`.
