# Strategi Trading untuk Akun Aqua Instant Pro

## Pendahuluan

Model Instant Pro menawarkan akses langsung ke akun pendanaan tanpa fase evaluasi.
Aturan yang diterapkan (berdasarkan dokumen internal AquaFunded) meliputi:

- **Trailing drawdown 4% dari ekuitas** — lantai ekuitas naik saat mencapai puncak baru dan tidak pernah turun kembali.
- **Tanpa batas daily drawdown** — tidak ada limit kerugian harian eksplisit, namun kill-switch tetap berlaku.
- **Kill-switch permanen**: bila floating loss menyentuh −2% dari saldo awal, akun ditutup permanen.
- **Payout**: trader harus mencatat minimal **5 hari profit** dengan profit per hari ≥ 0,5% dari saldo awal.
- **Aturan konsistensi**: profit hari terbaik tidak boleh melebihi **20% dari total profit** periode pembayaran.
- **Leverage forex** hingga 1:100, pembagian laba standar **80%**.

Prinsip pengembangan sistem dari *Building Reliable Trading Systems* (Keith Fitschen) menekankan
bahwa toleransi drawdown harus ditentukan lebih dulu — bukan target profit — dan bahwa keserakahan
adalah jebakan utama yang mendorong trader mengambil risiko berlebihan. Prinsip ini sangat relevan
untuk Instant Pro yang memiliki batas drawdown ketat dan penalti permanen jika melanggar.

---

## Konsekuensi dari Aturan Instant Pro

| Aturan | Implikasi Praktis |
|--------|-------------------|

| Trailing drawdown 4% | Lantai naik bersama ekuitas; ruang bernapas menyempit setelah profit besar. |
| Kill-switch −2% floating | Eksposur gabungan yang jatuh > −2% dari saldo awal menutup akun selamanya. |
| Tanpa batas daily loss | Fleksibilitas, tapi kill-switch −2% membuat risiko harian tetap ketat. |
| Konsistensi 20% | Satu hari jackpot menunda payout sampai total profit naik cukup besar. |
| 5 hari profit ≥ 0,5% | Strategi yang menghasilkan profit stabil lebih cocok daripada scalping bergejolak. |

---

## Prinsip Strategi yang Sesuai

### 1. Manajemen Risiko dan Ukuran Posisi

- **Risiko per posisi**: 0,25%–0,5% dari akun, batas operasional **0,4%**.
  Dengan kill-switch −2%, dua posisi yang salah bersamaan tidak boleh menutup akun.
- **Maksimal 2 posisi utama** bersamaan; total eksposur terbuka ≤ 0,8%.
- **Hindari overeksposur korelatif**: jangan buka beberapa pasangan yang bergerak searah secara bersamaan.
- **Stop-loss wajib** di setiap posisi — ditempatkan di area teknis yang logis (di luar swing terakhir)
  atau ATR × 1,5, sehingga kerugian individu ≤ 0,5%.
- **Catastrophic stop** juga wajib sebagai jaring pengaman terakhir.
- **Scale-out**: ambil sebagian profit di target awal (RR 1:2), pindahkan SL ke breakeven,
  biarkan sisa posisi berjalan ke target kedua (RR 1:3).

### 2. Distribusi Profit dan Konsistensi

- **Target harian 0,5%–1,0%**: cukup untuk memenuhi syarat payout tanpa membuat satu hari mendominasi.
- **Berhenti setelah target tercapai**: hindari membuka posisi baru bila profit harian sudah mencapai 0,5%–0,8%.
- **Hindari hari jackpot**: satu hari profit 4% memaksa total profit harus > 20 × 4% = 80% sebelum payout bisa diminta. Pertahankan distribusi merata.

### 3. Jenis Strategi yang Cocok

- **Trend-following intraday (pilihan utama)**: identifikasi tren H4/H1 (HH-HL bullish, LH-LL bearish),
  tunggu pullback ke Fibonacci 50% atau S/R, konfirmasi candlestick + RSI 14 / MACD.
  Entry split bisa digunakan jika harga kembali ke area entry.
- **Mean-reversion terkontrol**: hanya saat pasar jelas range; posisi lebih kecil, SL disiplin.
- **Breakout filter**: hindari breakout murni — lebih aman entry setelah retest.
  Breakout sering butuh stop lebih lebar yang rentan terhadap kill-switch −2%.
- **Session filter**: fokus pada sesi London (14:00–18:00 WIB) dan New York (20:00–23:00 WIB).
- **News filter**: hindari trading 30 menit sebelum/sesudah rilis data berdampak tinggi (NFP, FOMC, dll.).

### 4. Pencatatan dan Evaluasi

- **Jurnal harian**: catat entry, SL, target, lot, floating PnL terburuk, dan hasil setiap posisi.
- **Review mingguan**: hitung total profit, drawdown, dan profit hari terbaik.
  Jika profit hari terbaik mendekati 20% total, kurangi ukuran trade atau tutup profit lebih cepat.
- **Evaluasi strategi**: jika suatu setup menyebabkan drawdown > 1% atau sering mendekati kill-switch,
  hentikan dan evaluasi parameter. Hindari curve-fitting.

---

## Contoh Rencana Trading — Akun $100.000

| Parameter | Nilai |
|-----------|-------|

| Risiko per posisi | Maks $400 (0,4%) |
| Total risiko terbuka | Maks $800 (0,8%) |
| Pasangan utama | EURUSD, GBPUSD |
| Stop trading setelah | 2 loss berturut-turut |
| Batas loss mingguan | 2% ($2.000) |
| Target harian | $500–$800 (0,5%–0,8%) |
| Stop setelah target | Ya — tutup trading hari itu |
| Sesi | London 14:00–18:00 & NY 20:00–23:00 WIB |
| News blackout | 30 menit sebelum/sesudah rilis tinggi |
| Strategi | Trend-following H4/H1, entry pullback |
| RR target pertama | 1:2 |
| RR target kedua | 1:3 atau trailing stop |

---

## Penutup

Model Instant Pro menawarkan potensi pertumbuhan cepat, tetapi disiplin risiko adalah kunci keberhasilan.
Dengan membatasi risiko per trade, mengutamakan distribusi profit yang stabil, menghindari hari profit
yang terlalu besar, dan menggunakan strategi teknis yang teruji dengan stop-loss ketat, trader dapat
memanfaatkan akun Instant Pro tanpa melanggar ketentuan.

Prinsip dari literatur pengembangan sistem — prioritaskan toleransi drawdown, hindari keserakahan,
dan selalu evaluasi performa secara sistematis — tetap relevan sebagai kerangka kerja utama di
akun pendanaan jenis ini.
