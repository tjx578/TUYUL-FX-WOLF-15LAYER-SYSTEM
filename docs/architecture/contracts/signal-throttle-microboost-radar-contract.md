# SignalThrottle Microboost Radar Contract

Status: architecture contract. Runtime implementation is enforced in the
SignalThrottle log analyzer and Wolf constitutional pipeline; this file records
the boundary that those modules must preserve.

## Verdict utama

Benar: sistem bukan sekadar "tidak menemukan microboost"; sistem terlihat
sudah mengubah fungsi microboost menjadi terlalu bergantung pada verdict
eksekusi. Itu yang membuat microboost mati ketika semua input berakhir di
`NO_TRADE`.

Seharusnya:

```text
Microboost = radar tekanan / timing impulse
Bukan anak dari EXECUTE_BUY / EXECUTE_SELL
```

Pada log yang diringkas, semua `signal_throttle_check` masuk sebagai:

```text
status = skipped
reason = non_execute_verdict
verdict = NO_TRADE
```

Maka sistem berhenti sebelum pressure itu sempat dibentuk menjadi
block/microboost. Ini salah secara arsitektur SignalThrottle.

## 1. Fakta / Verified Data

Dari file dan rangkaian analisa sebelumnya, prinsip yang sudah ditetapkan
adalah: SignalThrottle adalah radar tekanan, bukan arah final. Arah final harus
dibaca dari price phase, struktur M15/H1, tradeplan readiness, dan lifecycle
decision. Data SignalThrottle harus dibentuk dulu menjadi pressure block,
microboost, allowed quorum, lalu baru dinilai menjadi pattern/action map.

Di file lain, kondisi serupa pernah muncul: `SignalThrottle` dan
`SignalThrottleIntel` aktif, tetapi `SignalWatchJSON`,
`SignalDecisionUpdateJSON`, dan `SignalJSON` semuanya nol; semua Intel masih
`final_direction = WAIT`. Itu menunjukkan engine masih berhenti di
pressure/intel awal dan belum naik ke decision/final layer.

Framework terbaru juga sudah mengoreksi bahwa microboost tidak boleh selalu
menunggu M15 close. Microboost seharusnya menjadi entry timing / pressure
trigger; price phase saat microboost muncul menentukan konteks arah; M15 close
hanya optional untuk kondisi ambigu, counter, reversal, atau conflict.

Kasus USDCAD sebelumnya membuktikan masalah lifecycle: microboost dan
SignalWatch muncul, tetapi ketika pressure block besar berhenti, sistem tidak
emit final decision/update. Analisa itu menyimpulkan sistem terlalu
event-driven oleh microboost trigger, bukan state-driven oleh lifecycle block.

## 2. Kenapa sistem "merubah logic microboost"?

Ada 5 penyebab paling mungkin.

### 1. Microboost sekarang tergantung `EXECUTE_*`, bukan raw pressure

Ini akar masalahnya.

Dari ringkasan:

```text
47 signal_throttle_check
47/47 skipped
reason = non_execute_verdict
verdict = NO_TRADE
```

Artinya logic sekarang kira-kira seperti ini:

```python
if verdict not in [
    "EXECUTE_BUY",
    "EXECUTE_SELL",
    "EXECUTE_REDUCED_RISK_BUY",
    "EXECUTE_REDUCED_RISK_SELL",
]:
    skip_microboost()
```

Ini salah untuk desain SignalThrottle.

Yang benar:

```python
if pair_seen_in_signal_throttle:
    update_pressure_state()

if pressure_state_meets_microboost_condition:
    emit_microboost_or_watch()

if direction_and_execution_ready:
    emit_signal_json()
```

Jadi `NO_TRADE` boleh memblok eksekusi, tapi tidak boleh memblok pembentukan
pressure intelligence.

### 2. Branch `NO_TRADE` hanya emit canary, bukan pressure event penuh

Dari ringkasan, branch `NO_TRADE` hanya mengeluarkan `signal_throttle_check`
canary dan mencoba shadow microboost. Itu membuat sistem punya data "ada
sesuatu", tapi tidak cukup kaya untuk masuk ke jalur:

```text
SignalThrottle -> MicroboostIntel -> MicroboostTable -> SignalWatchJSON
```

Akibatnya microboost count tetap nol, walaupun sebenarnya ada 47 event yang
bisa dipakai sebagai radar awal.

Ini mirip masalah yang pernah terlihat di log lain: pair bisa dominan, allowed
quorum bisa ada, timing valid bisa muncul, tetapi tetap tidak naik ke
Watch/Decision/Signal karena transisi ke Watch terlalu ketat atau hanya
menunggu microboost tertentu.

### 3. Parser offline masih legacy: hanya membaca `[SignalThrottle]`

Gap penting:

```text
signal_throttle_log_analyzer.py hanya membaca format [SignalThrottle]
event=signal_throttle_check terbaca 0/1001 sebagai SignalThrottle
```

Ini bukan masalah market. Ini masalah schema mismatch.

Kalau service engine sekarang emit:

```text
event = signal_throttle_check
```

tetapi parser hanya membaca:

```text
[SignalThrottle]
```

maka semua canary baru akan dianggap bukan data SignalThrottle. Akibatnya
analisa offline berkata "tidak ada microboost", padahal log runtime punya event
yang harus dinormalisasi dulu.

Fix-nya: buat normalizer yang menyatukan semua ini:

```text
[SignalThrottle]
signal_throttle_check
SignalThrottleIntel
MicroboostIntel
MicroboostTable
SignalWatchJSON
SignalDecisionUpdateJSON
SignalJSON
```

ke event model internal yang sama.

### 4. Threshold microboost terlalu mengunci ke "burst padat"

Threshold butuh minimal 5 event dalam 18-60 detik dengan density >= 8/min, atau
block lebih kuat. Pada data ini event per symbol terpecah kecil/tunggal, jadi
tidak lolos.

Threshold itu tidak salah untuk hot microboost, tapi salah kalau dipakai
sebagai satu-satunya pintu.

Karena dari logic terbaru, pressure punya beberapa bentuk:

```text
LOW_DENSITY_OPEN_LANE
TIMING_VALID_BLOCK
ALLOWED_CANARY_QUORUM
HOT_MICROBOOST
LATE_DENSE_PRESSURE
FRAGMENTED_THEME_ROTATION
```

Jadi kalau event tidak lolos hot microboost, sistem masih harus bisa
mengeluarkan:

```text
SignalThrottleIntel WAIT
PressureCandidate
TimingWatch
NoTradeReasoned
FinalExpired
```

Bukan langsung nol.

### 5. Sistem mencampur "valid signal" dengan "execution signal"

Ini bug kontrak lama.

Sekarang sistem seolah berpikir:

```text
kalau tidak executable -> tidak perlu microboost / tidak perlu final output
```

Padahal kontrak yang benar:

```text
signal_valid != valid_for_execution
```

Contoh output yang benar:

```json
{
  "event": "signal_decision_update_json",
  "symbol": "USDCAD",
  "signal_valid": true,
  "direction_valid": false,
  "valid_for_execution": false,
  "terminal_status": "NO_TRADE_REASONED",
  "reason": "Pressure seen but execution verdict remains NO_TRADE"
}
```

Jadi valid pressure tidak boleh hilang hanya karena belum valid eksekusi.

## 3. Kesimpulan teknis paling keras

Sistem tidak seharusnya menunggu `EXECUTE_*` untuk menghitung microboost.

Urutan sekarang yang bermasalah:

```text
L12 verdict
-> jika EXECUTE baru SignalThrottle/Microboost aktif
-> jika NO_TRADE hanya canary
-> microboost tidak berkembang
```

Urutan yang benar:

```text
Raw engine event / throttle check
-> normalize event
-> pressure block builder
-> microboost / allowed quorum / timing block
-> price phase classifier
-> SignalWatch / DecisionUpdate
-> baru execution gate menentukan SignalJSON final
```

Dengan kata lain:

```text
NO_TRADE boleh menghentikan order.
NO_TRADE tidak boleh menghentikan radar.
```

## 4. Asumsi / Estimasi berbasis data

Berdasarkan ringkasan log, perubahan logic microboost diperkirakan terjadi
karena salah satu patch sebelumnya mencoba membuat sistem lebih aman dari final
signal palsu, lalu efek sampingnya:

```text
microboost ikut dikunci ke final verdict
```

Niatnya benar: mencegah SignalJSON palsu.

Efek sampingnya salah: pressure/microboost ikut mati.

Yang seharusnya dikunci ketat hanya:

```text
SignalJSON final execution
valid_for_execution=true
order-ready trade plan
```

Yang tidak boleh dikunci ketat:

```text
SignalThrottle pressure
MicroboostIntel
SignalWatchJSON
SignalDecisionUpdateJSON
NoTradeReasoned event
```

## 5. Rekomendasi perbaikan paling praktis

### Patch 1 - Pisahkan telemetry dari execution

Tambahkan rule:

```python
# selalu update pressure state kalau event pair muncul
pressure_event = normalize_signal_throttle_event(log)

if pressure_event.symbol:
    pressure_state.update(pressure_event)

# verdict hanya memengaruhi eksekusi, bukan pressure
execution_allowed = verdict in EXECUTE_VERDICTS
```

### Patch 2 - Treat `signal_throttle_check` sebagai pressure input

Parser harus membaca:

```python
SIGNAL_THROTTLE_EVENT_NAMES = {
    "SignalThrottle",
    "signal_throttle_check",
    "SignalThrottleIntel",
}
```

Lalu map:

```json
{
  "event": "signal_throttle_check",
  "verdict": "NO_TRADE",
  "status": "skipped",
  "reason": "non_execute_verdict"
}
```

menjadi:

```json
{
  "event_type": "PRESSURE_CANARY",
  "eligible_for_pressure_block": true,
  "eligible_for_execution": false
}
```

### Patch 3 - Tambahkan output terminal untuk NO_TRADE pressure

Kalau 47 event semua `NO_TRADE`, sistem tetap harus emit minimal:

```json
{
  "event": "signal_decision_update_json",
  "terminal_status": "NO_TRADE_REASONED",
  "signal_valid": false,
  "pressure_seen": true,
  "microboost_detected": false,
  "reason": "All throttle checks were non-execute verdicts; pressure did not meet microboost threshold."
}
```

Ini penting agar dashboard tidak terlihat "mati".

### Patch 4 - Buat 3 level microboost

Jangan cuma satu threshold.

```text
Level 1: PRESSURE_CANARY
- 1-4 event
- belum microboost
- masuk radar

Level 2: MICROBOOST_WATCH
- event cluster cukup
- density sedang/tinggi
- butuh price context

Level 3: MICROBOOST_TIMING_VALID
- phase + structure + RR mendukung
- bisa naik ke Watch/Decision/Signal
```

Dengan begitu 47 event `NO_TRADE` tidak jadi final signal, tapi tetap tercatat
sebagai pressure telemetry.

### Patch 5 - Jangan jadikan M15 close default gate

Gunakan mode:

```text
DIRECT       = microboost + phase decisive
WATCH        = counter/ambigu/reversal/conflict
MANAGEMENT   = late pressure / protect profit
NO_TRADE     = pressure ada tapi tidak layak
```

Ini selaras dengan koreksi sebelumnya bahwa M15 close bukan wajib untuk semua
signal; ia hanya dipakai untuk kondisi ambigu/counter/reversal/conflict.

## 6. Final decision

Penyebab utama microboost tidak update bukan karena market tidak aktif, tetapi
karena logic microboost sekarang terlalu dikunci ke `EXECUTE_*` verdict dan
parser belum mengenali `signal_throttle_check` sebagai pressure event.

Fix paling penting:

```text
Microboost harus hidup dari pressure stream,
bukan dari execution verdict.
```

Kalimat paling tajamnya:

```text
EXECUTE adalah pintu order.
Microboost adalah radar.
Jangan pasang radar setelah pintu order.
```

Kalau tidak dibetulkan, setiap kali L12 memberi `NO_TRADE`, sistem akan tampak
"aman", tapi buta terhadap pressure build-up yang seharusnya menjadi bahan
SignalWatch atau terminal `NO_TRADE_REASONED`.
