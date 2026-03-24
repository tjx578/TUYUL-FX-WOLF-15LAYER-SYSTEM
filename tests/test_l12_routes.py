from __future__ import annotations

import time

from api import l12_routes


def _make_verdict(
    pair: str, verdict: str = "HOLD", confidence: float = 0.25, cached_at: float | None = None, **extra: object
) -> dict:
    """Build a minimal realistic verdict payload for tests."""
    base = {
        "symbol": pair,
        "verdict": verdict,
        "confidence": confidence,
        "direction": extra.pop("direction", verdict.split("_")[-1] if verdict.startswith("EXECUTE") else None),
        "scores": extra.pop("scores", {}),
        "_cached_at": cached_at if cached_at is not None else time.time(),
    }
    base.update(extra)
    return base


def _patch_pairs(monkeypatch, pairs: list[str]) -> None:
    monkeypatch.setattr(
        l12_routes,
        "AVAILABLE_PAIRS",
        [{"symbol": p, "name": p, "enabled": True} for p in pairs],
    )


def test_fetch_pairs_includes_configured_cross_pair() -> None:
    symbols = {pair["symbol"] for pair in l12_routes.fetch_pairs() if isinstance(pair.get("symbol"), str)}
    assert "GBPJPY" in symbols


def test_fetch_all_verdicts_reads_configured_pairs(monkeypatch) -> None:
    _patch_pairs(monkeypatch, ["GBPJPY", "EURUSD"])
    # Clear in-memory cache from previous test runs
    l12_routes._verdict_cache._data = None

    now = time.time()

    def fake_get_verdict(pair: str):
        if pair == "GBPJPY":
            return _make_verdict("GBPJPY", cached_at=now)
        return None

    monkeypatch.setattr(l12_routes, "get_verdict", fake_get_verdict)

    result = l12_routes.fetch_all_verdicts()

    assert result["status"] == "ok"
    assert result["mode"] == "LIVE"
    assert result["count"] == 1
    assert "GBPJPY" in result["verdicts"]
    assert result["verdicts"]["GBPJPY"]["symbol"] == "GBPJPY"
    assert result["verdicts"]["GBPJPY"]["verdict"] == "HOLD"
    assert result["verdicts"]["GBPJPY"]["_meta"]["cache_ttl_seconds"] == l12_routes.VERDICT_TTL_SEC
    assert result["reason"] is None


def test_build_pipeline_data_includes_execution_map_passthrough() -> None:
    verdict_data = {
        "verdict": "EXECUTE_BUY",
        "confidence": 0.88,
        "execution": {"entry_price": 1.1, "stop_loss": 1.09, "take_profit_1": 1.12},
        "gates": {"passed": 9, "total": 9, "gate_1_tii": "PASS"},
        "execution_map": {
            "pair": "EURUSD",
            "timestamp": "2026-03-03T00:00:00+00:00",
            "layers_executed": ["L0", "L1", "L2", "L12", "L13", "L14"],
            "engines_invoked": ["RegimeClassifier", "FusionIntegrator", "TRQ3DEngine"],
            "halt_reason": None,
            "constitutional_verdict": "EXECUTE_BUY",
            "layer_timings_ms": {"L1": 3.2, "L2": 4.1},
            "dag": {
                "topology": ["L1", "L2", "L4"],
                "batches": [["L1", "L2"], ["L4"]],
                "edges": [{"from": "L1", "to": "L4"}, {"from": "L2", "to": "L4"}],
            },
        },
    }

    pipeline = l12_routes._build_pipeline_data("EURUSD", verdict_data)

    assert pipeline["execution_map"]["pair"] == "EURUSD"
    assert "L12" in pipeline["execution_map"]["layers_executed"]
    assert pipeline["execution_map"]["constitutional_verdict"] == "EXECUTE_BUY"
    assert pipeline["profiling"]["layer_timings_ms"]["L1"] == 3.2
    assert pipeline["dag"]["topology"] == ["L1", "L2", "L4"]


def test_build_pipeline_data_generates_execution_map_fallback() -> None:
    verdict_data = {
        "verdict": "HOLD",
        "confidence": "LOW",
        "gates": {"passed": 3, "total": 9, "gate_1_tii": "FAIL"},
    }

    pipeline = l12_routes._build_pipeline_data("GBPJPY", verdict_data)

    execution_map = pipeline["execution_map"]
    assert execution_map["pair"] == "GBPJPY"
    assert execution_map["constitutional_verdict"] == "HOLD"
    assert isinstance(execution_map["layers_executed"], list)
    assert len(execution_map["layers_executed"]) == len(pipeline["layers"])
    assert "profiling" in pipeline
    assert "dag" in pipeline
    assert isinstance(pipeline["dag"]["edges"], list)


def test_build_pipeline_data_includes_signal_conditioning_observability() -> None:
    verdict_data = {
        "verdict": "HOLD",
        "confidence": 0.42,
        "system": {
            "latency_ms": 88,
            "signal_conditioning": {
                "samples_out": 55,
                "noise_ratio": 0.21,
                "microstructure_quality_score": 0.79,
                "source": "candle_H1",
            },
        },
        "gates": {"passed": 4, "total": 9, "gate_1_tii": "PASS"},
    }

    pipeline = l12_routes._build_pipeline_data("EURUSD", verdict_data)
    obs = pipeline["observability"]["signal_conditioning"]

    assert obs["samples_out"] == 55
    assert obs["noise_ratio"] == 0.21
    assert obs["microstructure_quality_score"] == 0.79
    assert obs["source"] == "candle_H1"


def test_extract_hold_block_reason_prefers_cached_field() -> None:
    raw = {
        "last_hold_block_reason": "GOVERNANCE_HOLD:stale_preserved",
        "errors": ["WARMUP_INSUFFICIENT:H1"],
    }
    assert l12_routes._extract_hold_block_reason(raw) == "GOVERNANCE_HOLD:stale_preserved"


def test_internal_verdict_path_reports_key_and_warmup(monkeypatch) -> None:
    monkeypatch.setattr(
        l12_routes,
        "AVAILABLE_PAIRS",
        [
            {"symbol": "EURUSD", "name": "EURUSD", "enabled": True},
            {"symbol": "GBPJPY", "name": "GBPJPY", "enabled": True},
        ],
    )

    def fake_get_verdict(pair: str):
        if pair == "EURUSD":
            return {
                "symbol": "EURUSD",
                "verdict": "HOLD",
                "_cached_at": 100.0,
                "governance": {"action": "HOLD", "reasons": ["stale_preserved"]},
                "last_hold_block_reason": "GOVERNANCE_HOLD:stale_preserved",
            }
        return None

    class _FakeBus:
        def check_warmup(self, symbol: str, min_bars: dict[str, int]):
            if symbol == "EURUSD":
                return {"ready": True, "bars": {"H1": 30}, "required": {"H1": 20}, "missing": {}}
            return {"ready": False, "bars": {"H1": 5}, "required": {"H1": 20}, "missing": {"H1": 15}}

    monkeypatch.setattr(l12_routes, "get_verdict", fake_get_verdict)
    monkeypatch.setattr(l12_routes, "RedisContextReader", lambda: _FakeBus())
    monkeypatch.setattr(l12_routes.time, "time", lambda: 160.0)

    payload = l12_routes.fetch_internal_verdict_path()
    rows = {row["pair"]: row for row in payload["pairs"]}

    assert rows["EURUSD"]["redis_key_exists"] is True
    assert rows["EURUSD"]["warmup_status"]["ready"] is True
    assert rows["EURUSD"]["governance_action"] == "HOLD"
    assert rows["EURUSD"]["verdict_age_seconds"] == 60.0
    assert rows["EURUSD"]["last_hold_block_reason"] == "GOVERNANCE_HOLD:stale_preserved"

    assert rows["GBPJPY"]["redis_key_exists"] is False
    assert rows["GBPJPY"]["warmup_status"]["ready"] is False


def test_internal_verdict_path_survives_redis_error(monkeypatch) -> None:
    monkeypatch.setattr(
        l12_routes,
        "AVAILABLE_PAIRS",
        [
            {"symbol": "EURUSD", "name": "EURUSD", "enabled": True},
        ],
    )

    def _boom(_pair: str):
        raise RuntimeError("redis unavailable")

    class _FakeBus:
        def check_warmup(self, _symbol: str, _min_bars: dict[str, int]):
            return {"ready": False, "bars": {"H1": 0}, "required": {"H1": 20}, "missing": {"H1": 20}}

    monkeypatch.setattr(l12_routes, "get_verdict", _boom)
    monkeypatch.setattr(l12_routes, "RedisContextReader", lambda: _FakeBus())

    payload = l12_routes.fetch_internal_verdict_path(pair="EURUSD")
    row = payload["pairs"][0]

    assert payload["redis_ok"] is False
    assert payload["redis_error"] == "redis unavailable"
    assert row["pair"] == "EURUSD"
    assert row["redis_key_exists"] is False
    assert row["warmup_status"]["ready"] is False


# ── Regression tests: /api/v1/verdict/all schema stability ───────────

_STALE_THRESHOLD_SEC = 300.0


def test_verdict_all_live_fresh(monkeypatch) -> None:
    """Fresh verdicts -> mode=LIVE, status=ok, all verdicts present."""
    _patch_pairs(monkeypatch, ["EURUSD", "GBPUSD"])
    l12_routes._verdict_cache._data = None

    now = time.time()
    monkeypatch.setattr(l12_routes, "get_verdict", lambda p: _make_verdict(p, cached_at=now - 10))

    result = l12_routes.fetch_all_verdicts()

    assert result["status"] == "ok"
    assert result["mode"] == "LIVE"
    assert result["count"] == 2
    assert result["reason"] is None
    assert result["stale_seconds"] is not None
    assert result["stale_seconds"] < _STALE_THRESHOLD_SEC
    assert "EURUSD" in result["verdicts"]
    assert "GBPUSD" in result["verdicts"]
    assert "timestamp" in result


def test_verdict_all_stale_with_snapshot(monkeypatch) -> None:
    """All verdicts older than 5 min -> mode=DEGRADED, still returned."""
    _patch_pairs(monkeypatch, ["EURUSD", "XAUUSD"])
    l12_routes._verdict_cache._data = None

    stale_ts = time.time() - 600  # 10 min old
    monkeypatch.setattr(l12_routes, "get_verdict", lambda p: _make_verdict(p, cached_at=stale_ts))

    result = l12_routes.fetch_all_verdicts()

    assert result["status"] == "degraded"
    assert result["mode"] == "DEGRADED"
    assert result["reason"] == "ALL_STALE"
    assert result["count"] == 2
    # Stale verdicts are still returned (not filtered out)
    assert "EURUSD" in result["verdicts"]
    assert "XAUUSD" in result["verdicts"]
    assert result["stale_seconds"] >= 600


def test_verdict_all_no_snapshot(monkeypatch) -> None:
    """No verdicts in Redis -> mode=NO_SNAPSHOT_YET, empty items."""
    _patch_pairs(monkeypatch, ["EURUSD", "GBPUSD"])
    l12_routes._verdict_cache._data = None

    monkeypatch.setattr(l12_routes, "get_verdict", lambda _p: None)

    result = l12_routes.fetch_all_verdicts()

    assert result["status"] == "no_data"
    assert result["mode"] == "NO_SNAPSHOT_YET"
    assert result["reason"] == "NO_SNAPSHOT_YET"
    assert result["count"] == 0
    assert result["verdicts"] == {}
    assert result["stale_seconds"] is None


def test_verdict_all_hold_verdicts_not_filtered(monkeypatch) -> None:
    """HOLD verdicts (no TP/SL) must NOT be silently dropped."""
    _patch_pairs(monkeypatch, ["EURUSD"])
    l12_routes._verdict_cache._data = None

    now = time.time()
    monkeypatch.setattr(
        l12_routes,
        "get_verdict",
        lambda _p: _make_verdict("EURUSD", "HOLD", confidence=0.25, cached_at=now, take_profit_1=None, stop_loss=None),
    )

    result = l12_routes.fetch_all_verdicts()

    assert result["count"] == 1
    assert "EURUSD" in result["verdicts"]
    assert result["verdicts"]["EURUSD"]["verdict"] == "HOLD"


def test_filter_actionable_verdicts_keeps_execute_only() -> None:
    """_filter_actionable_verdicts returns only EXECUTE with valid TP/SL."""
    now = time.time()
    verdicts = {
        "EURUSD": _make_verdict("EURUSD", "HOLD", cached_at=now),
        "GBPUSD": _make_verdict(
            "GBPUSD", "EXECUTE", cached_at=now, direction="BUY", take_profit_1=1.30, stop_loss=1.28
        ),
        "XAUUSD": _make_verdict(
            "XAUUSD", "EXECUTE_REDUCED_RISK", cached_at=now, direction="SELL", take_profit_1=1900, stop_loss=1950
        ),
    }

    result = l12_routes._filter_actionable_verdicts(verdicts)

    assert "EURUSD" not in result  # HOLD excluded
    assert "GBPUSD" in result
    assert "XAUUSD" in result


# ---------------------------------------------------------------------------
# Issue #8 regression: pipeline layer status must reflect actual outcomes
# ---------------------------------------------------------------------------


def test_build_pipeline_data_l12_fail_when_gates_below_threshold() -> None:
    """L12 status must be 'fail' when pass_count < 7 of 9 gates."""
    verdict_data = {
        "verdict": "NO_TRADE",
        "confidence": 0.2,
        "gates": {"passed": 4, "total": 9, "gate_1_tii": "FAIL", "gate_5_montecarlo": "FAIL"},
    }
    pipeline = l12_routes._build_pipeline_data("EURUSD", verdict_data)
    l12_layer = next(lyr for lyr in pipeline["layers"] if lyr["id"] == "L12")
    assert l12_layer["status"] == "fail"


def test_build_pipeline_data_l12_warn_when_gates_7_of_9() -> None:
    """L12 status must be 'warn' when exactly 7 of 9 gates pass."""
    verdict_data = {
        "verdict": "HOLD",
        "confidence": 0.5,
        "gates": {"passed": 7, "total": 9, "gate_1_tii": "PASS"},
    }
    pipeline = l12_routes._build_pipeline_data("EURUSD", verdict_data)
    l12_layer = next(lyr for lyr in pipeline["layers"] if lyr["id"] == "L12")
    assert l12_layer["status"] == "warn"


def test_build_pipeline_data_gate_mapped_layer_fail_from_gate() -> None:
    """Layer L8 (TII) status must be 'fail' when gate_1_tii is FAIL."""
    verdict_data = {
        "verdict": "NO_TRADE",
        "confidence": 0.3,
        "gates": {"passed": 5, "total": 9, "gate_1_tii": "FAIL"},
    }
    pipeline = l12_routes._build_pipeline_data("EURUSD", verdict_data)
    l8_layer = next(lyr for lyr in pipeline["layers"] if lyr["id"] == "L8")
    assert l8_layer["status"] == "fail"


def test_build_pipeline_data_gate_mapped_layer_pass_from_gate() -> None:
    """Layer L7 (Monte Carlo) status must be 'pass' when gate_5_montecarlo is PASS."""
    verdict_data = {
        "verdict": "EXECUTE",
        "confidence": 0.88,
        "gates": {"passed": 9, "total": 9, "gate_5_montecarlo": "PASS", "gate_1_tii": "PASS"},
    }
    pipeline = l12_routes._build_pipeline_data("EURUSD", verdict_data)
    l7_layer = next(lyr for lyr in pipeline["layers"] if lyr["id"] == "L7")
    assert l7_layer["status"] == "pass"


def test_build_pipeline_data_skip_vs_pass_for_unexecuted_layers() -> None:
    """Un-executed layers must show 'skip', not 'pass'."""
    verdict_data = {
        "verdict": "NO_TRADE",
        "confidence": 0.15,
        "gates": {"passed": 3, "total": 9, "gate_1_tii": "FAIL"},
        "execution_map": {
            "pair": "EURUSD",
            "timestamp": "2026-03-24T00:00:00Z",
            "layers_executed": ["L1", "L2", "L12"],
            "engines_invoked": [],
            "halt_reason": None,
            "constitutional_verdict": "NO_TRADE",
            "layer_timings_ms": {"L1": 2.0, "L2": 3.0, "L12": 5.0},
            "dag": {"topology": ["L1", "L2", "L12"], "batches": [["L1", "L2"], ["L12"]], "edges": []},
        },
    }

    pipeline = l12_routes._build_pipeline_data("EURUSD", verdict_data)
    layer_statuses = {lyr["id"]: lyr["status"] for lyr in pipeline["layers"]}

    # Un-executed layers must all be 'skip', not 'pass' or 'fail'
    # Exception: L8 (TII) is gate-mapped to gate_1_tii=FAIL, so it shows 'fail'
    skip_layers = [lid for lid, st in layer_statuses.items() if st == "skip"]
    pass_layers = [lid for lid, st in layer_statuses.items() if st == "pass"]

    # 11 layers are skip (12 not in layers_executed minus L8 which is gate-mapped)
    assert len(skip_layers) == 11, f"Expected 11 skip layers, got {len(skip_layers)}: {skip_layers}"
    # Frontend executedCount = total - skipCount = 15 - 11 = 4
    total = len(pipeline["layers"])
    skip_count = len(skip_layers)
    executed_count = total - skip_count
    assert executed_count == 4, f"Expected executedCount=4, got {executed_count}"

    # passCount / executedCount should read '2/4':
    #   L1 -> pass, L2 -> pass, L8 -> fail (gate-mapped), L12 -> fail (3/9 gates < 7 threshold)
    assert len(pass_layers) == 2  # L1 + L2
    l12_status = layer_statuses["L12"]
    assert l12_status == "fail"  # 3/9 gates < 7 threshold
