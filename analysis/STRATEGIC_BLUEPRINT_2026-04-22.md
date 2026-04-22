# Tuyul Kartel FX — Strategic Blueprint

## Verdict Recovery, Adaptive Wiring, Ingest Readiness, Source Orchestration

**Tanggal:** 22 April 2026
**Engine:** TUYUL-FX-WOLF-15LAYER-SYSTEM
**Sumber bukti:** `logs.1776831884452.json` (analisis Anda) + audit kode runtime di `analysis/`, `constitution/`, `core/core_fusion/`, `journal/`, `state/`
**Status doktrin:** orchestrate before acting → verify before finalizing → persist what matters
**Dokumen ini menggantikan:** semua draft sebelumnya tentang "adaptive threshold susah keluar verdict"

---

## 0. Eksekutif Singkat (Untuk Pembaca yang Cuma Punya 60 Detik)

Sistem Anda tidak rusak di tempat yang Anda kira. Setelah audit kode lapangan, tiga hal jadi jelas. Pertama, **hampir seluruh tulang punggung 15-layer SUDAH ADA**: `verdict_engine.py` (L12) mengimplementasikan 10 gate konstitusional plus Kelly edge guard, `l12_router_evaluator.py` melakukan 9-gate scoring, `gatekeeper.py` melakukan validasi 9 gate finer-grain, `heartbeat_classifier.py` punya state machine HEALTHY/DEGRADED/NO_PRODUCER, dan `core/core_fusion/adaptive_threshold.py` benar-benar punya `recompute()` yang menghasilkan `adjustment_factor` antara 0.85 dan 1.15 berdasarkan meta_drift dan integrity_index. Jadi argumen "tidak ada adaptive" salah secara ringan — adaptasinya ada, tapi tidak terpasang.

Kedua, ada **empat circuit putus** yang membuat semua pekerjaan baik di atas tidak menghasilkan verdict yang sehat: (1) `adaptive_threshold.recompute()` tidak pernah dipanggil oleh L7, L8, atau L9 — ia adalah pulau tanpa jembatan; (2) `verdict_engine.generate_l12_verdict()` tidak memvalidasi `ingest_health` sebelum mengeluarkan verdict, sehingga sekalipun heartbeat NO_PRODUCER, L12 tetap memproses; (3) `gatekeeper.py` punya 9 gate tetapi tidak punya `_gate_ingest_health` — ia membabi-buta percaya pada candidate yang masuk; (4) L9 mendapatkan `available_sources` dari dict keys lokal (`smc`, `liquidity_score`, `dvg_confidence`) tanpa kontrak publisher — kalau builder upstream crash, L9 hanya tahu "tidak_siap" tanpa diagnostic forward.

Ketiga, **bottleneck nyata di log adalah evidence incomplete, bukan threshold ketat**. Integrity L8 di angka 0.38–0.45 vs required 0.75 (gap 0.30+) bukan kasus "kurang sedikit" — itu kasus L7/L9 source belum sah, sehingga komponen integrity L8 di-fed oleh nol-padding. Menurunkan threshold di kondisi ini sama dengan memberikan eksekusi pada bukti palsu, dan itu adalah jalan tercepat menuju blow-up account, terutama di lingkungan prop-firm.

Solusi yang paling maju bukan menulis ulang sistem. Solusinya adalah **wiring lima hal** dengan kontrak yang ketat: IngestStateConsumer sebagai gate wajib dikonsultasi gatekeeper dan verdict_engine; SourceBuilderOrchestrator dengan publisher registry untuk smc/liquidity/divergence; ProbabilityClusterFallback untuk L7 saat history per-symbol di bawah 30; SourceAwareIntegrity untuk L8 yang menghormati source completeness sebelum menggunakan threshold tinggi; dan AdaptiveThresholdGovernor sebagai bridge resmi terakhir yang baru diaktifkan setelah source dan ingest sehat. Semuanya berlapis governance: shadow → canary → promote, dengan budget perubahan threshold harian maksimum 8%, hard gate yang tidak boleh diadaptasi (missing source, NO_PRODUCER, L12 unsigned), dan verification telemetry yang membuat setiap perubahan bisa diaudit. Empat sampai enam minggu kerja, urut, reversible, dan safety-first.

### 0.1 Keputusan Implementasi Final

Blueprint ini **valid sebagai roadmap utama**, tetapi implementasinya ke repo harus bertahap dan safety-first. Urutan kerja resmi untuk repo ini adalah:

```text
P0  Freeze execution / pastikan execution tetap off
P1  IngestStateConsumer + gate ingest di Gatekeeper dan VerdictEngine
P2  SourceBuilderOrchestrator untuk L9: smc/liquidity/divergence
P3  ProbabilityClusterFallback untuk L7
P4  SourceAwareIntegrity untuk L8
P5  AdaptiveThresholdGovernor shadow-mode
P6  Canary → promote → baru evaluasi P1-D / execution
```

Doktrin implementasinya tegas: **circuit putus diperbaiki dulu, threshold adaptif belakangan**. Evidence incomplete tidak boleh diselesaikan dengan menurunkan threshold, dan adaptive threshold tidak boleh dipakai untuk menutupi source L9 yang missing, L7 simulations=0, atau ingest yang belum HEALTHY.

---

## 1. Bukti yang Jadi Dasar Blueprint

### 1.1 Yang Anda Sudah Verifikasi dari Log

Anda telah melakukan parsing menyeluruh terhadap `logs.1776831884452.json` dan menemukan distribusi berikut yang saya gunakan tanpa modifikasi: 1.085 entries (772 info, 313 error) dalam jendela 2026-04-22 04:21:39 UTC sampai 04:24:20 UTC. Failure profile menunjukkan L1 FAIL=27, L2 FAIL=94, L3 FAIL=96, L7 constitutional FAIL=108, L8 constitutional FAIL=129, L9 constitutional FAIL=114. Top blocker: WARMUP_INSUFFICIENT=159, MTA_HIERARCHY_VIOLATED=135, INTEGRITY_SCORE_BELOW_MINIMUM=129, REQUIRED_STRUCTURE_SOURCE_MISSING=95, REQUIRED_PROBABILITY_SOURCE_MISSING=64, UPSTREAM_L2_NOT_CONTINUABLE=94, LOW_CONTEXT_COHERENCE=54, LOW_ALIGNMENT_BAND=47, EDGE_STATUS_INVALID=36. Heartbeat snapshot menunjukkan ingest_state=DEGRADED_REST_FALLBACK, provider=STALE, ws_connected=False, producer_fresh=False, symbols_ready=0/30. L8 integrity terlihat 0.376–0.451 vs required 0.75. L7 trade history 27/30 dengan simulations=0 dan win_probability=0.0. L9 missing_sources mencakup `['smc','liquidity','divergence']` dengan builder_state seringkali "not_ready" atau "partial".

Catatan penting tentang verifikasi: dalam audit otomatis, file log spesifik `logs.1776831884452.json` tidak terlihat di mounted folder repo maupun session uploads pada saat audit dijalankan, sehingga angka di atas saya percayakan kepada parsing Anda sendiri. Implikasinya hanya satu — angka boleh jadi sedikit bergeser bila parsing diulang, tetapi pola yang Anda tarik (Phase3 sistemik gagal di L7/L8/L9, ingest sempat DEGRADED, evidence incomplete, threshold ketat tetapi bukan akar utama) sepenuhnya konsisten dengan bukti runtime kode di poin berikutnya.

### 1.2 Yang Saya Verifikasi Langsung di Kode

Audit langsung terhadap delapan file kunci memberikan bukti yang lebih tajam dari sekadar angka log. Pada `analysis/layers/L7_constitutional.py` baris 90–91, threshold MID_THRESHOLD=0.55 dan HIGH_THRESHOLD=0.67 hardcoded; MIN_SAMPLE_WARN=30 di baris 92 menjelaskan kenapa 27/30 trade history memicu fallback. Pada `analysis/layers/L8_constitutional.py` baris 92–93, HIGH_THRESHOLD=0.88 dan MID_THRESHOLD=0.75 hardcoded; flag rescue `_ENABLE_L8_LFS_RESCUE` di baris 96 default off, dan thresholds rescue (`_LFS_RESCUE_SCORE_MIN=0.72`, `_LFS_RESCUE_LRCE_MIN=0.970`, `_LFS_RESCUE_DRIFT_MAX=0.0045`, `_LFS_RESCUE_GRAD_MAX=0.005`) live di kode bukan di YAML. Pada `analysis/layers/L9_constitutional.py` baris 91–94, HIGH_THRESHOLD=0.80, MID_THRESHOLD=0.65, dan REQUIRED_STRUCTURE_SOURCES tuple (`"smc","liquidity","divergence"`) hardcoded; method `_structure_source_flags` di baris 274 menderive availability dari dict lokal `l9_analysis.get("smc")`, `l9_analysis.get("liquidity_score")>0`, `l9_analysis.get("dvg_confidence")>0` tanpa kontrak publisher.

Pada `core/core_fusion/adaptive_threshold.py`, kelas `AdaptiveThresholdController` punya `recompute(frpc_data)` yang menghasilkan `AdaptiveUpdate` dict berisi adjustment_factor terkalibrasi formula `_clamp(1.0 + (md*12.0) - (max(0.0, ii-0.96)*2.0), 0.85, 1.15)` di baris 87 — tetapi kelas ini tidak punya method `get_adjusted_threshold(layer, base_threshold)` dan tidak ada satu pun call-site di L7/L8/L9 yang mengimpor atau memanggilnya. Pada `constitution/verdict_engine.py` baris 485, `generate_l12_verdict(synthesis, governance_penalty)` adalah canonical path; ia tidak memanggil `heartbeat_classifier`, tidak menulis hasil ke Redis secara otomatis, dan validasi field synthesis hanya ada di baris 516. Pada `constitution/l12_router_evaluator.py` baris 152–162, threshold 9-gate hardcoded: EXECUTE_MIN_SCORE=0.65, EXECUTE_REDUCED_MIN_SCORE=0.50, HOLD_MIN_SCORE=0.40, HARD_GATES `{FOUNDATION_OK, STRUCTURE_OK, RISK_CHAIN_OK, FIREWALL_OK}`. Pada `state/heartbeat_classifier.py` baris 225–245, fungsi `classify_ingest_health(process_status, provider_status)` punya logika tri-state HEALTHY/DEGRADED/NO_PRODUCER yang benar — tetapi tidak ada konsumer di pipeline verdict yang memanggilnya untuk menghentikan eksekusi saat NO_PRODUCER. Pada `constitution/gatekeeper.py` baris 55–78, sembilan gate (`_gate_integrity, _gate_tii, _gate_probability, _gate_rr, _gate_position, _gate_timeframe, _gate_market_law, _gate_execution_rule, _gate_completeness`) berjalan urut, tetapi tidak ada `_gate_ingest_health`.

### 1.3 Konfirmasi Atas Hipotesis Anda

Hipotesis Anda bahwa adaptive threshold belum benar-benar live di runtime constitutional gates terbukti benar dengan tingkat presisi tertinggi. Modulnya ada, fungsinya ada, formulanya ada, tetapi outlet API-nya nol. Ini bukan masalah konsep — ini masalah wiring satu hari kerja. Hipotesis Anda bahwa L9 source missing adalah penyebab utama juga benar; bukan hanya itu, audit kode mengungkap bahwa L9 bahkan tidak punya kontrak publisher untuk smc/liquidity/divergence sama sekali. L9 pasrah dengan apa yang ada di dict yang dilemparkan pemanggil. Hipotesis Anda bahwa L8 0.75 mungkin terlalu tinggi adalah benar secara prinsip tetapi tidak boleh dijawab dengan menurunkan angka. Audit menunjukkan integritas L8 dihitung dari komponen yang termasuk skor L7 dan L9 — kalau dua input itu nol karena source belum sah, integrity wajar jatuh ke 0.40-an. Threshold 0.75 hanya berbahaya jika dipaksa pasif sambil source upstream belum disehatkan.

---

## 2. SPARC Specification — "Tuyul Verdict Recovery"

### 2.1 Objective Canonical

Mengembalikan kemampuan engine TUYUL-FX-WOLF menerbitkan L12 final verdict yang sah (EXECUTE, EXECUTE_REDUCED_RISK, HOLD, atau NO_TRADE) dengan governance yang menjamin tidak ada eksekusi terjadi di atas evidence yang missing source, ingest degraded, atau adaptive threshold yang melewati budget keamanan harian. Pada fase awal, ukuran sukses utama adalah **zero unsafe verdict**, bukan banyaknya verdict.

### 2.2 Acceptance Criteria

Sebuah signal dianggap "lolos pipeline" hanya jika delapan kondisi berikut terpenuhi secara simultan dan terbukti di telemetry: ingest heartbeat menunjukkan HEALTHY (process ALIVE + provider ALIVE) selama minimum 30 detik berturut-turut sebelum verdict diproses; L1 context coherence mencapai minimum band setelah adaptasi yang sah; L2 MTA alignment lolos hierarchy check dengan diagnostics per-timeframe terpublish; L7 mendapatkan probability source dengan simulations >= 1000 atau status CONDITIONAL terjustifikasi via cluster fallback; L8 integrity berada di atas threshold yang disesuaikan governor, dengan source completeness >=0.80 sebagai prasyarat; L9 mendapatkan minimal dua dari tiga required sources (smc, liquidity, divergence) dalam status FRESH dengan builder_state=ready atau partial-with-justification; L11 RR berada di atas 1.5 atau di atas threshold yang berlaku per regime; L12 menerbitkan verdict yang signed dengan signal_id unik dan ditulis ke Redis key `verdict:{symbol}:{ts}` dengan TTL 60 detik.

Sebagai metrik observasional, dalam jendela 7 hari pertama setelah deployment paket P0–P4, target utamanya adalah zero verdict yang berhasil dieksekusi saat ingest_state != HEALTHY, zero verdict EXECUTE pada simulations=0 atau win_probability=0.0, zero overrides adaptive yang melebihi budget 8% perubahan harian, dan penurunan nyata pada `source_builder_state=not_ready`. Target jumlah verdict boleh dipantau sebagai telemetry, tetapi **tidak menjadi acceptance hard gate** pada fase awal.

### 2.3 Non-Goals (Eksplisit)

Blueprint ini tidak menulis ulang arsitektur 15-layer; ia hanya menyambung kabel yang sudah ada dan menambahkan sedikit komponen baru. Blueprint ini tidak melonggarkan threshold L7/L8/L9 secara permanen; semua perubahan threshold runtime hanya boleh terjadi melalui AdaptiveThresholdGovernor dengan jejak audit. Blueprint ini tidak meminta perubahan pada strategy.yaml di propfirm_manager kecuali untuk parameter governance baru. Blueprint ini tidak menyentuh execution layer (broker connectors, order management) — eksekusi tetap menjadi konsumen pasif dari verdict yang sudah signed. Blueprint ini tidak menjanjikan profitability — ia menjanjikan signal flow yang sehat dan auditable; profitability adalah konsekuensi independen dari kualitas strategi.

### 2.4 Edge Cases yang Wajib Ditangani

Pertama, kasus weekend/market closed di mana provider STALE adalah sah dan bukan failure: heartbeat_classifier sudah menangani via flag market session, tetapi gatekeeper baru harus menyadari konteks ini. Kedua, kasus split-brain di mana process ALIVE tetapi WS sudah lama disconnect dan REST fallback aktif: harus diklasifikasi DEGRADED dan eksekusi tidak boleh diizinkan walau data terlihat fresh. Ketiga, kasus L9 partial source di mana hanya liquidity yang available tetapi smc dan divergence missing: SourceBuilderOrchestrator harus menerbitkan diagnostic eksplisit tentang penyebab missing per source, dan L9 harus tetap FAIL dengan pesan yang lebih informatif. Keempat, kasus L7 cold-start setelah deploy dengan zero history: harus menggunakan ProbabilityClusterFallback (cluster majors, JPY, commodity, AUD/NZD cross) dan menandai status sebagai CONDITIONAL — bukan PASS. Kelima, kasus adaptive governor mendeteksi anomalous drift (md > 0.02): harus auto-freeze ke base threshold dan emit alert ke L15.

### 2.5 Success Metrics

Empat KPI primary mengukur kesehatan pipeline pada fase awal. Bypass Count = jumlah verdict EXECUTE yang dieksekusi tanpa ingest HEALTHY, target = 0 selalu. Source Override Count = jumlah verdict EXECUTE pada L9 dengan available_sources < 2, target = 0 selalu. Phantom Probability Count = jumlah verdict EXECUTE pada L7 dengan simulations=0, target = 0 selalu. Source Completeness Index = rata-rata harian dari (available_sources / required_sources) di L9, target ≥ 0.85.

Empat KPI secondary dipakai sebagai telemetry perkembangan, bukan hard gate awal. Ingest Live Ratio = waktu HEALTHY / waktu trading session, target ≥ 0.99. Adaptive Stability = jumlah hari di mana adaptive_factor menyimpang lebih dari 8% dari base, target = 0 dalam jendela 7 hari rolling. Builder Readiness Recovery = proporsi evaluasi L9 dengan `source_builder_state != not_ready`, target naik minggu-ke-minggu. Adoption Rate = (jumlah verdict EXECUTE atau EXECUTE_REDUCED_RISK per hari) / (jumlah signal yang lewat L1 untuk evaluasi) — dipantau setelah P5 live, bukan dipaksakan pada P1–P4.

---

## 3. Arsitektur — Lima Komponen Wajib

Catatan penting: urutan penjelasan arsitektur di bawah ini **bukan** urutan implementasi. Urutan implementasi resmi mengikuti Section 0.1 dan Section 5, dimulai dari ingest hard gate lalu source orchestration, baru adaptive threshold shadow-mode.

### 3.1 AdaptiveThresholdGovernor (Bridge & Policy)

Letak: extend `core/core_fusion/adaptive_threshold.py` + buat `constitution/adaptive_threshold_governor.py`.

Tanggung jawab governor adalah menjadi satu-satunya pintu masuk yang sah bagi L7, L8, dan L9 untuk mendapatkan threshold runtime yang disesuaikan. Ia membungkus `AdaptiveThresholdController.recompute()` yang sudah ada dan menambahkan empat lapis policy: source completeness gate (tidak ada penyesuaian saat L9 source incomplete), daily delta budget (perubahan kumulatif harian dibatasi 8%), shadow/canary/promote state machine (perubahan baru menjalani tujuh hari shadow sebelum mempengaruhi verdict), dan signed audit trail (setiap penyesuaian disimpan ke `audit:adaptive:{layer}:{ts}` dengan reasoning lengkap).

Kontrak API minimal:

```python
# constitution/adaptive_threshold_governor.py (NEW FILE)
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass(frozen=True)
class AdjustedThreshold:
    layer: str                          # "L7" | "L8" | "L9"
    metric: str                         # "win_probability" | "integrity" | "structure_score"
    base: float
    adjusted: float
    adjustment_factor: float            # in [0.85, 1.15]
    mode: Literal["shadow", "canary", "live"]
    source_completeness: float          # in [0, 1]
    decision_reason: str
    audit_id: str

class AdaptiveThresholdGovernor:
    """
    Single sanctioned gateway for runtime threshold adjustments.
    All L7/L8/L9 constitutional gates MUST consult this before evaluating.
    """

    def get_adjusted(
        self,
        layer: str,
        metric: str,
        base_threshold: float,
        frpc_data: dict,
        source_completeness: float,
        regime_tag: Optional[str] = None,
    ) -> AdjustedThreshold:
        # 1. Hard gate: source incomplete -> return base unchanged
        if source_completeness < 0.80:
            return self._return_base(layer, metric, base_threshold, "source_incomplete")
        # 2. Daily budget gate
        if not self._budget_ok(layer, metric):
            return self._return_base(layer, metric, base_threshold, "daily_budget_exceeded")
        # 3. Compute adjustment via existing controller
        update = self._controller.recompute(frpc_data)
        adj_factor = update.get("proposed", {}).get("adjustment_factor", 1.0)
        # 4. Resolve mode (shadow/canary/live) per layer+metric registry
        mode = self._resolve_mode(layer, metric)
        adjusted = base_threshold * adj_factor if mode == "live" else base_threshold
        # 5. Audit
        audit_id = self._audit(layer, metric, base_threshold, adjusted, adj_factor, mode, frpc_data)
        return AdjustedThreshold(
            layer=layer, metric=metric, base=base_threshold,
            adjusted=adjusted, adjustment_factor=adj_factor,
            mode=mode, source_completeness=source_completeness,
            decision_reason="ok", audit_id=audit_id,
        )
```

Patch sisi L7 (`analysis/layers/L7_constitutional.py`):

```python
# Tambahkan di top-level import
from constitution.adaptive_threshold_governor import get_governor

# Di dalam evaluate(), sebelum band derivation:
governor = get_governor()
src_complete = self._compute_source_completeness(l7_analysis)  # new helper
threshold_obj = governor.get_adjusted(
    layer="L7",
    metric="win_probability",
    base_threshold=MID_THRESHOLD,         # 0.55
    frpc_data=upstream_output.get("frpc_snapshot", {}),
    source_completeness=src_complete,
    regime_tag=upstream_output.get("regime_tag"),
)
effective_mid = threshold_obj.adjusted   # use this, not MID_THRESHOLD
# Persist for telemetry
result["adaptive_threshold_audit"] = threshold_obj.__dict__
```

Patch identik diterapkan ke L8 (metric="integrity") dan L9 (metric="structure_score"). Yang baru: helper `_compute_source_completeness` di tiap layer mengembalikan rasio (sumber tersedia / sumber dibutuhkan) — di L9 ini sudah ada via `_structure_source_flags`, di L7 ini berasal dari rasio history/30, di L8 ini dari rasio komponen integrity yang non-null.

### 3.2 IngestStateConsumer (Hard Gate Wajib)

Letak: `state/ingest_state_consumer.py` (NEW) + patch ke `constitution/gatekeeper.py` dan `constitution/verdict_engine.py`.

Tanggung jawab IngestStateConsumer adalah menyediakan satu source-of-truth yang dapat dikonsultasi murah oleh setiap konsumen pipeline. Implementasinya membungkus `heartbeat_classifier.read_ingest_health()` dengan caching Redis (TTL 5 detik), state-transition logging, dan predicate `is_blocking()` yang mengembalikan True jika ingest_state berada di NO_PRODUCER atau DEGRADED dengan provider_age > 60 detik.

```python
# state/ingest_state_consumer.py (NEW FILE)
from state.heartbeat_classifier import read_ingest_health, IngestHealthState

class IngestStateConsumer:
    CACHE_TTL_SEC = 5
    BLOCKING_STATES = {IngestHealthState.NO_PRODUCER}
    DEGRADED_TOLERATED_MAX_AGE = 60

    def get_state(self) -> dict:
        cached = self._redis.get("cache:ingest_state")
        if cached:
            return json.loads(cached)
        health = read_ingest_health(self._redis)
        payload = {
            "state": health.state.name,
            "process_age": health.process_age_seconds,
            "provider_age": health.provider_age_seconds,
            "ts": time.time(),
        }
        self._redis.setex("cache:ingest_state", self.CACHE_TTL_SEC, json.dumps(payload))
        return payload

    def is_blocking(self) -> tuple[bool, str]:
        s = self.get_state()
        if s["state"] in {x.name for x in self.BLOCKING_STATES}:
            return True, f"ingest_no_producer:age={s['process_age']:.1f}s"
        if s["state"] == "DEGRADED" and s["provider_age"] > self.DEGRADED_TOLERATED_MAX_AGE:
            return True, f"ingest_degraded_too_long:age={s['provider_age']:.1f}s"
        return False, "ingest_ok"
```

Patch `constitution/gatekeeper.py` — tambahkan gate ingest sebagai gate pertama:

```python
# Di __init__:
from state.ingest_state_consumer import IngestStateConsumer
self._ingest = IngestStateConsumer(redis=...)

# Di evaluate(), gates list — taruh PERTAMA:
gates = [
    self._gate_ingest_health,    # NEW: must run first
    self._gate_completeness,
    self._gate_integrity,
    # ... rest unchanged
]

def _gate_ingest_health(self, candidate: dict) -> tuple[bool, str]:
    blocking, reason = self._ingest.is_blocking()
    if blocking:
        return False, f"ingest_blocked:{reason}"
    return True, "ingest_ok"
```

Patch `constitution/verdict_engine.py` — di `generate_l12_verdict()` segera setelah validasi field synthesis:

```python
# After _validate_required_fields(synthesis):
ingest = IngestStateConsumer(redis=...)
blocking, reason = ingest.is_blocking()
if blocking:
    return {
        "symbol": synthesis["symbol"],
        "verdict": "NO_TRADE",
        "verdict_reason": f"ingest_unhealthy:{reason}",
        "confidence": "LOW",
        "direction": None,
        "gates": {"ingest_gate": "FAIL"},
        "audit": {"ingest_state_audit_id": ingest.last_audit_id},
    }
```

Konsekuensi: untuk pertama kalinya, sistem tidak bisa secara teknis menerbitkan EXECUTE saat ingest tidak HEALTHY. Ini menutup risiko terbesar (eksekusi atas data palsu).

### 3.3 SourceBuilderOrchestrator (Kontrak Publisher untuk L9)

Letak: `analysis/orchestrators/source_builder_orchestrator.py` (NEW).

Tanggung jawab orchestrator adalah memformalkan publisher contract untuk smc, liquidity, dan divergence. Saat ini L9 hanya mengintip dict; orchestrator membuat tiga producer eksplisit yang masing-masing menjamin schema, freshness, dan diagnostic.

```python
# analysis/orchestrators/source_builder_orchestrator.py (NEW FILE)
from dataclasses import dataclass
from typing import Protocol, Optional
from analysis.layers.L9_smc import SmcEngine
from analysis.exhaustion_dvg_fusion_engine import ExhaustionDivergenceFusionEngine
from engines.v11.liquidity_sweep_scorer import LiquiditySweepScorer

@dataclass
class SourceSnapshot:
    name: str
    score: float
    valid: bool
    confidence: float
    age_seconds: float
    publisher_id: str
    schema_version: str
    diagnostics: dict

class SourcePublisher(Protocol):
    def build(self, candles: dict, context: dict) -> Optional[SourceSnapshot]: ...

class SourceBuilderOrchestrator:
    REQUIRED = ("smc", "liquidity", "divergence")
    MAX_SOURCE_AGE_SEC = 15

    def __init__(self):
        self._publishers = {
            "smc":        SmcPublisher(),
            "liquidity":  LiquidityPublisher(),
            "divergence": DivergencePublisher(),
        }

    def build_for_l9(self, candles: dict, context: dict) -> dict:
        snapshots = {}
        diagnostics = {"missing": [], "stale": [], "errored": []}
        for name in self.REQUIRED:
            try:
                snap = self._publishers[name].build(candles, context)
                if snap is None:
                    diagnostics["missing"].append(name)
                elif snap.age_seconds > self.MAX_SOURCE_AGE_SEC:
                    diagnostics["stale"].append(name)
                else:
                    snapshots[name] = snap
            except Exception as e:
                diagnostics["errored"].append({"name": name, "error": str(e)})
        builder_state = (
            "ready"     if len(snapshots) == 3 else
            "partial"   if len(snapshots) >= 1 else
            "not_ready"
        )
        return {
            "smc":            snapshots.get("smc").__dict__ if "smc" in snapshots else None,
            "liquidity_score": snapshots.get("liquidity").score if "liquidity" in snapshots else 0.0,
            "dvg_confidence": snapshots.get("divergence").confidence if "divergence" in snapshots else 0.0,
            "structure_sources": {k: (k in snapshots) for k in self.REQUIRED},
            "source_builder_state": builder_state,
            "source_diagnostics": diagnostics,
            "publisher_metadata": {k: v.publisher_id for k, v in snapshots.items()},
        }
```

Implementasi `SmcPublisher`, `LiquidityPublisher`, `DivergencePublisher` adalah thin adapters yang membungkus engine yang sudah ada (`L9_smc.SmcEngine`, `LiquiditySweepScorer`, `ExhaustionDivergenceFusionEngine`). Setiap adapter mengembalikan `SourceSnapshot` lengkap dengan publisher_id, schema_version, age_seconds, dan diagnostics — atau None jika tidak ada signal valid (bukan exception). Pipeline hook (di `analysis/v11/pipeline_hook.py` atau `analysis/signal_conditioner.py`) dipatch untuk memanggil orchestrator sebelum L9_constitutional.evaluate(), dan output orchestrator dilewatkan sebagai argumen `l9_analysis`.

Konsekuensi: L9 akan mendapatkan diagnostics yang jujur. `missing_sources=['smc']` sekarang akan dibarengi alasan ("SmcEngine returned None: insufficient pivot count" atau "publisher errored: KeyError 'h4_candles'") yang bisa di-log ke L15 dan dipakai untuk fix engineering yang tepat sasaran.

### 3.4 SourceAwareIntegrity (Patch L8)

Letak: extend `analysis/layers/L8_constitutional.py` + helper baru.

Filosofi: integrity threshold 0.75 sah untuk kondisi source FULL, tetapi tidak adil untuk kondisi PARTIAL. Solusi paling maju bukan menurunkan 0.75, tetapi membuat L8 source-aware: tiga mode threshold dengan governance ketat.

```python
# Di L8_constitutional.py, di dalam evaluate() setelah computing integrity score:

source_completeness = self._derive_source_completeness(l8_analysis, upstream_output)
# returns one of: "FULL" (>=0.95), "PARTIAL" (>=0.60), "DEGRADED" (<0.60)

if source_completeness == "FULL":
    effective_threshold = governor.get_adjusted(
        "L8", "integrity", MID_THRESHOLD, frpc_data, 1.0
    ).adjusted   # 0.75 base, may adapt to 0.69-0.81 in live mode
    integrity_mode = "FULL_SOURCE"
elif source_completeness == "PARTIAL":
    effective_threshold = 0.60   # warning-only floor
    integrity_mode = "PARTIAL_SOURCE_WARN_ONLY"
    # Force result max severity to WARN and cap final outcome at HOLD / shadow-only
    self._cap_severity_at_warn = True
    self._force_hold_only = True
else:  # DEGRADED
    effective_threshold = None   # gate auto-FAIL
    integrity_mode = "DEGRADED_SOURCE_HOLD"
    self._force_fail = True

result["integrity_mode"] = integrity_mode
result["integrity_threshold_used"] = effective_threshold
```

Konsekuensi: dalam kondisi log saat ini (source incomplete), L8 akan FAIL secara eksplisit dengan kode `DEGRADED_SOURCE_HOLD` alih-alih `INTEGRITY_SCORE_BELOW_MINIMUM`. Untuk mode `PARTIAL_SOURCE_WARN_ONLY`, outcome final tetap harus dibatasi maksimal `HOLD` atau shadow-only; ia tidak boleh membuka jalur EXECUTE hanya karena threshold warning floor dipenuhi.

### 3.5 ProbabilityClusterFallback (Patch L7)

Letak: `analysis/probability_cluster_fallback.py` (NEW) + patch ke `analysis/layers/L7_probability.py`.

Filosofi: cold-start atau symbol baru tidak boleh menghasilkan `simulations=0, win_probability=0.0` yang merusak L8 integrity. Solusinya adalah cluster fallback dengan transparent labeling.

```python
# analysis/probability_cluster_fallback.py (NEW FILE)
SYMBOL_CLUSTERS = {
    "majors":      {"EURUSD","GBPUSD","USDJPY","USDCHF","USDCAD","AUDUSD","NZDUSD"},
    "jpy_cross":   {"EURJPY","GBPJPY","AUDJPY","NZDJPY","CHFJPY","CADJPY"},
    "metals":      {"XAUUSD","XAGUSD"},
    "aud_nzd":     {"AUDNZD","EURAUD","EURNZD","GBPAUD","GBPNZD"},
}

class ProbabilityClusterFallback:
    MIN_CLUSTER_SAMPLES = 30
    MIN_OWN_SAMPLES_PREFERRED = 30

    def derive(self, symbol: str, own_history: list[dict], cluster_pool: dict) -> dict:
        if len(own_history) >= self.MIN_OWN_SAMPLES_PREFERRED:
            return self._monte_carlo(own_history, source="own")
        cluster = self._resolve_cluster(symbol)
        cluster_history = cluster_pool.get(cluster, [])
        if len(cluster_history) >= self.MIN_CLUSTER_SAMPLES:
            mc = self._monte_carlo(cluster_history, source=f"cluster:{cluster}")
            mc["status"] = "CONDITIONAL"   # not full-strength PASS
            mc["confidence_penalty"] = 0.10
            return mc
        return {
            "win_probability": None, "simulations": 0,
            "status": "INSUFFICIENT", "source": "none",
        }
```

Patch di `L7_probability.py` menggunakan fallback ini. Hasil dengan `status="CONDITIONAL"` diizinkan masuk ke L7_constitutional dengan bobot terkurangi (0.10 confidence penalty), bukan `win_probability=0.0` yang menjebak. Hasil dengan `status="INSUFFICIENT"` memicu L7 mengembalikan FAIL eksplisit dengan kode `INSUFFICIENT_HISTORY_NO_CLUSTER` — bukan menerbitkan angka palsu.

---

## 4. Performance & Latency Budget

Hot path verdict (dari tick masuk sampai L12 verdict tertulis ke Redis) saat ini tidak ter-instrumented secara end-to-end di kode yang saya audit. Blueprint ini menetapkan budget eksplisit dan rekomendasi instrumentasi.

Target latency p50/p95/p99 per layer dalam milisecond, untuk satu signal pada satu symbol pada satu timeframe: L1 context (5/15/40), L2 MTA (10/30/80), L3 technical (15/50/120), L4 session scoring (3/10/25), L5 psychology (5/15/40), L6 risk (8/25/60), L7 probability incl. Monte Carlo 1k sims (40/120/300), L8 integrity (8/25/60), L9 SourceBuilderOrchestrator+L9_constitutional (20/60/150), L10 sizing (5/15/40), L11 RR (3/10/25), L12 verdict_engine (10/30/80). Total budget end-to-end: p50 132ms, p95 410ms, p99 1020ms. Hitungan ini realistis untuk Python single-process; jika dijalankan dengan async, paralelisasi L1-L5 (independent) dapat memangkas total p50 sampai sekitar 90ms.

Tiga area paling menjanjikan untuk optimisasi: pertama, AgentDB+HNSW untuk pattern recall di L7/L9 — ganti linear scan history dengan HNSW indexed lookup, perkiraan speedup 50-100x untuk query "top-k similar past trade contexts". Kedua, batch processing di Monte Carlo L7 — saat ini per-call simulation, ganti dengan vectorized numpy/numba, perkiraan speedup 5-10x. Ketiga, Redis pipeline untuk source publish/read di SourceBuilderOrchestrator — kurangi 30+ round-trip Redis menjadi 2-3 pipelined batches, perkiraan latency reduction 60-80%.

Benchmark harness wajib dibangun bersamaan dengan P3. Harness mengukur tiga skenario: cold-start (no cache, no warmup), warm steady-state (after 10 minutes uptime), dan stress (30 symbols simultaneous). Laporan harian terbit ke `journal/benchmark/{date}.json` dan auto-trigger alert bila p95 melebihi budget di atas selama 3 hari berturut.

---

## 5. Phased Rollout — P0 sampai P6 (Diurutkan Aman)

### P0 — Freeze Execution / Pastikan Execution Tetap Off (Hari 0)

Sebelum apa pun, pastikan `EXECUTION_ENABLED=0` secara eksplisit di runtime yang benar-benar aktif. Jika execution memang belum aktif di Railway/runtime saat ini, requirement minimum adalah bukti startup log yang jelas bahwa execution masih off. Verdict tetap boleh diproduksi untuk telemetry, tetapi tidak ada order yang dikirim ke broker. Ini adalah safety net selama empat sampai enam minggu kerja berikutnya. Verifikasi: cek log untuk konfirmasi bahwa adapter eksekusi mengembalikan `{"sent": false, "reason": "execution_disabled"}` untuk setiap verdict EXECUTE, atau log startup yang menyatakan execution adapter disabled.

### P1 — Ingest Readiness Hardening (Hari 1-3)

Tambahkan `IngestStateConsumer` ke `state/`. Patch `gatekeeper.py` dengan `_gate_ingest_health` sebagai gate pertama. Patch `verdict_engine.generate_l12_verdict()` untuk mengembalikan NO_TRADE saat ingest blocking. Tambahkan instrumented logging: setiap transisi state (HEALTHY→DEGRADED, DEGRADED→NO_PRODUCER, dan reverse) ditulis ke `audit:ingest:transitions`. Acceptance: dalam shadow run 24 jam, target `bypass_count = 0` (zero verdict EXECUTE saat ingest tidak HEALTHY).

### P2 — SourceBuilderOrchestrator (Hari 4-10)

Implement `analysis/orchestrators/source_builder_orchestrator.py` dengan tiga publisher: SmcPublisher (membungkus L9_smc.SmcEngine), LiquidityPublisher (membungkus LiquiditySweepScorer), DivergencePublisher (membungkus ExhaustionDivergenceFusionEngine). Setiap publisher harus pass kontrak: schema_version, publisher_id, age_seconds, diagnostics non-null. Patch `signal_conditioner.py` untuk memanggil orchestrator sebelum L9_constitutional. Acceptance: dalam shadow run 48 jam dengan 30 symbols, `available_sources >= 2` dalam minimal 70% evaluasi, dan `source_diagnostics.errored` ≤ 5% dari total evaluasi.

### P3 — ProbabilityClusterFallback untuk L7 (Hari 11-16)

Implement `analysis/probability_cluster_fallback.py`. Patch `L7_probability.py` untuk menggunakan fallback saat own history < 30 trades. Hasil fallback harus berstatus `CONDITIONAL`, bukan PASS penuh, dan membawa confidence penalty eksplisit. Acceptance: `phantom_probability_count = 0`, distribusi L7 `status` mencakup `CONDITIONAL` untuk symbol cold-start, dan `simulations=0` tidak pernah membuka jalur EXECUTE.

### P4 — SourceAwareIntegrity untuk L8 (Hari 17-22)

Implement source-aware integrity di `L8_constitutional.py` (tiga mode FULL/PARTIAL/DEGRADED). Mode `PARTIAL_SOURCE_WARN_ONLY` harus tetap membatasi outcome final maksimal `HOLD` atau shadow-only. Acceptance: distribusi L8 `integrity_mode` mencakup ketiga nilai dengan reasoning yang jelas, source incomplete tidak pernah PASS karena threshold lowering, dan telemetry L8 mencatat `integrity_mode` serta `integrity_threshold_used`.

### P5 — AdaptiveThresholdGovernor Shadow-Mode (Hari 23-30)

Tambahkan `constitution/adaptive_threshold_governor.py`. Patch `L7_constitutional.py`, `L8_constitutional.py`, `L9_constitutional.py` untuk memanggil `governor.get_adjusted()` sebelum band derivation. Implementasikan empat lapis policy: source completeness gate, daily delta budget 8%, shadow/canary/promote state machine, signed audit trail. Mode awal untuk semua adjustments adalah `"shadow"` (compute tetapi tidak apply). Acceptance: dalam shadow run 7 hari, `adaptive_factor` tercatat di setiap evaluation, distribusi adjustment_factor terlihat sehat (median dekat 1.0, tail ±0.10), `delta_budget_exceeded_count = 0`, dan tidak ada perubahan live verdict akibat adaptive shadow.

### P6 — Canary → Promote → Baru Evaluasi P1-D / Execution (Hari 31+)

Hanya setelah P0–P5 lolos verification gate dan minimal 72 jam telemetry stabil di shadow mode, promote satu metric pada satu waktu dari `"shadow"` ke `"canary"` (mempengaruhi 10% verdict secara random) ke `"live"` (semua verdict). Urutan promosi: L9 structure_score (paling rendah risikonya, sumber sudah dikontrak), L8 integrity (medium), L7 win_probability (paling sensitif). Setiap promosi diobservasi minimum 72 jam sebelum lanjut ke metric berikutnya. Evaluasi P1-D / execution hanya boleh dibuka setelah canary-promote bersih. Jika execution akhirnya diaktifkan kembali, gunakan rate-limit awal: max 1 trade per 30 menit per symbol, max 3 concurrent positions total. Trigger rollback otomatis: kembalikan `EXECUTION_ENABLED=0` jika dalam 24 jam terakhir terjadi minimal salah satu: bypass_count > 0, source_override_count > 0, phantom_probability_count > 0, atau drawdown harian > batas prop firm.

---

## 6. Risk Register

Risiko tertinggi adalah eksekusi di atas data degraded — diatasi oleh P1 IngestStateConsumer. Risiko kedua adalah adaptive threshold yang adapt liar — diatasi oleh daily budget 8% di P3 dan shadow mode wajib selama tujuh hari. Risiko ketiga adalah cold-start symbol baru menerbitkan L7 simulations=0 — diatasi ProbabilityClusterFallback di P4. Risiko keempat adalah source publisher crash silent — diatasi diagnostics eksplisit di SourceBuilderOrchestrator dan alert L15. Risiko kelima adalah verdict_engine schema drift karena nested dict fragility — mitigasinya adalah canary release per metric dan rollback button via env flag.

Risiko medium yang patut diawasi: lock contention di Redis saat 30 symbols simultaneous query ingest_state (mitigasi: TTL cache 5 detik), drift formula adaptive (mitigasi: periodic recalibration via L14 + manual review tiap bulan), dan model regime tag tidak akurat (mitigasi: regime tag awal hanya digunakan untuk telemetry, belum untuk threshold scaling).

Risiko rendah tetapi worth flagging: dependency pada Redis availability untuk ingest cache (mitigasi: fallback langsung baca heartbeat tanpa cache), python single-process latency saat 30 symbols (mitigasi: P2 pipelined Redis + numba di Monte Carlo bila p95 budget terlampaui).

---

## 7. Verification Gate

Sebelum signed-off untuk production, lima gate berikut wajib lulus dengan bukti telemetry yang dilampirkan ke commit message dan diarsipkan di `journal/verification/{run-id}.json`.

Gate Clarity: setiap perubahan threshold, gate baru, atau patch wiring memiliki entry di `docs/CHANGELOG_VERDICT_RECOVERY.md` dengan rationale dan reference ke section blueprint ini. Gate Suitability: P3 shadow run telemetry menunjukkan distribusi adjustment_factor sehat dan zero budget violations. Gate Security: tidak ada credential, secret, atau account state masuk ke synthesis dict L12; verdict signing key dikelola via secret manager bukan env var; audit trail tidak dapat dihapus tanpa privileged role. Gate Performance: benchmark harness P3 menunjukkan p95 end-to-end ≤ 410ms dan p99 ≤ 1020ms di steady state 30 symbols. Gate Final Verification: minimal tiga independent agent (saya menyarankan: code-reviewer specialist, security auditor, performance benchmark agent) menjalankan review independen pada kode P1–P5 sebelum P6.

---

## 8. Memory Writeback (Doktrin "Persist What Matters")

Lima fakta kunci wajib ditulis ke memory namespace `project/tuyul-kartel-fx/strategic-blueprint-2026-04-22`. Pertama, decision: AdaptiveThresholdGovernor adalah satu-satunya jalur sah perubahan threshold runtime, hard gate (missing source, NO_PRODUCER, L12 unsigned, risk breach) tidak boleh diadaptasi. Kedua, finding: `verdict_engine.py`, `gatekeeper.py`, dan `core_fusion/adaptive_threshold.py` ada tetapi tidak terhubung ke heartbeat_classifier sebelum patch. Ketiga, architecture: lima komponen (Governor, IngestConsumer, SourceOrchestrator, SourceAwareIntegrity, ProbabilityClusterFallback) menyusun "wiring layer" yang menyambung modul existing. Keempat, risk: zero EXECUTE tolerance saat ingest tidak HEALTHY adalah trade-off lebih ketat dari sebelumnya, harus dikomunikasikan ke trading team. Kelima, rollout: urutan resmi adalah P0 execution-off, P1 ingest hard gate, P2 L9 source orchestration, P3 L7 probability fallback, P4 L8 source-aware integrity, P5 adaptive shadow-mode, P6 canary/promote lalu baru evaluasi execution.

Tambahan namespaces: `coordination/<run-id>` untuk shadow/canary/live promotion logs, `architecture/verdict_recovery` untuk diagram dan ADR, `verification/<P3-shadow-run-id>` untuk telemetry data telah lolos gate.

---

## 9. Pertanyaan yang Sering Muncul (Diantisipasi)

Apakah menurunkan L8 dari 0.75 ke angka lebih rendah lebih cepat? Secara teknis ya, tetapi itu adalah jalan menuju eksekusi atas evidence palsu. Solusi yang lebih maju adalah membuat threshold source-aware: 0.75 untuk source FULL (governance dengan adaptive), 0.60 sebagai warning-only floor untuk PARTIAL, hard FAIL untuk DEGRADED. Untuk mode PARTIAL, outcome final tetap harus dibatasi maksimal HOLD atau shadow-only. Ini menghormati bahwa 0.75 sah pada kondisi yang benar dan tidak adil pada kondisi yang salah.

Apakah blueprint ini memerlukan rebuild 15-layer? Tidak. Audit menunjukkan bahwa L1-L15 secara struktur sudah ada dan jalan; yang missing adalah lima komponen wiring/glue dan beberapa kontrak schema. Total estimasi line-of-code baru di bawah 2.000, total file baru lima, total file dipatch enam.

Berapa lama dari mulai sampai bisa execution lagi? Jika tim bekerja serial dengan dedicated developer: P1 tiga hari, P2 tujuh hari, P3 sepuluh hari, P4 tujuh hari, P5 tujuh hari, P6 satu hari plus ramp-up bertahap. Total empat sampai enam minggu kalender bila tidak ada blocker. Jika diparallelkan dengan dua developer (satu fokus orchestrator/source, satu fokus governor/gates), bisa dipersingkat 30-40%.

Apakah blueprint ini mengganggu trading saat ini? Tidak. P0 freeze execution adalah prasyarat tetapi sifatnya reversible dengan satu env var. Selama P1-P5, sistem terus memproduksi telemetry dan log untuk continuous learning ke L13/L14. Eksekusi kembali aktif di P6 setelah verification gate lolos.

Apakah ada plan B kalau adaptive threshold tetap tidak menolong? Ya. AdaptiveThresholdGovernor dapat di-disable global dengan env var `ADAPTIVE_THRESHOLD_MODE=force_base`, mengembalikan semua threshold ke nilai base hardcoded. Sistem tetap berjalan dengan IngestStateConsumer dan SourceBuilderOrchestrator yang sudah independen dari governor. Dalam skenario ini, kontribusi adaptive threshold dianggap nol dan team fokus pada perbaikan source quality.

---

## 10. Final Doctrine (Penutup)

Tiga prinsip yang membentuk blueprint ini, sesuai master orchestrator skill: orchestrate before acting, verify before finalizing, persist what matters.

Bukti runtime menunjukkan sistem Anda lebih dekat ke kondisi sehat dari yang terlihat di permukaan log. Yang membuat verdict susah keluar bukan kurangnya intelijen — sistem ini punya 10-gate verdict engine, 9-gate gatekeeper, 4 phase chain adapter, dan adaptive controller yang formula-nya sudah dikalibrasi. Yang membuat verdict susah keluar adalah lima circuit putus yang tidak terlihat sampai diaudit langsung. Memperbaikinya bukan pekerjaan rebuild; ini pekerjaan wiring dengan governance yang ketat dan rollout yang sabar.

Solusi paling maju di sini bukan algoritma baru atau paradigma baru. Solusinya adalah komitmen pada doktrin: threshold tidak diturunkan untuk menutupi evidence yang missing; eksekusi tidak terjadi di atas data yang tidak HEALTHY; adaptive threshold tidak boleh dijadikan langkah pertama; perubahan adaptive tidak dipromote ke live tanpa shadow seven-day; setiap keputusan threshold meninggalkan jejak audit yang bisa dirollback. Empat sampai enam minggu disiplin pada doktrin ini akan mengembalikan signal flow yang sehat dan, lebih penting, akan membuat sistem ini layak menyentuh modal real account tanpa ketakutan blow-up yang tidak perlu.
