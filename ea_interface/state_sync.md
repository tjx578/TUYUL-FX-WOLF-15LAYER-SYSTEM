# EA ↔ TUYUL FX STATE SYNC CONTRACT

## Prinsip Mutlak
- EA = EXECUTOR ONLY
- EA tidak menghitung signal
- EA tidak menentukan RR
- EA tidak boleh market execution

## Command dari Sistem ke EA
- PLACE  → pasang pending order
- CANCEL → batalkan pending order
- HOLD   → tidak melakukan apa pun

## State dari EA ke Sistem
- IDLE           → tidak ada order aktif atau pending
- PENDING_ACTIVE
- FILLED
- CANCELLED

## Sinkronisasi
- Sistem menulis command ke `storage/ea_commands/`
- EA membaca command secara periodik
- EA mengirim status ke `storage/ea_state/`

## Larangan
- EA mengubah SL/TP
- EA membuka market order
- EA membuka trade tanpa command
