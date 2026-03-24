from api import l12_routes


def test_fetch_pairs_includes_configured_cross_pair() -> None:
    symbols = {pair["symbol"] for pair in l12_routes.fetch_pairs() if isinstance(pair.get("symbol"), str)}
    assert "GBPJPY" in symbols


def test_fetch_all_verdicts_reads_configured_pairs(monkeypatch) -> None:
    monkeypatch.setattr(
        l12_routes,
        "AVAILABLE_PAIRS",
        [
            {"symbol": "GBPJPY", "name": "GBPJPY", "enabled": True},
            {"symbol": "EURUSD", "name": "EURUSD", "enabled": True},
        ],
    )

    def fake_get_verdict(pair: str):
        # Provide a verdict that passes _filter_valid_verdicts (score > 0, tp1 > 0, sl > 0, direction set)
        if pair == "GBPJPY":
            return {
                "symbol": pair,
                "verdict": "HOLD",
                "score": 0.7,
                "take_profit_1": 145.50,
                "stop_loss": 144.00,
                "direction": "BUY",
            }
        return None

    # Reset the module-level cache so the test always hits the fetch path
    l12_routes._verdict_cache._last_fetch = 0.0

    monkeypatch.setattr(l12_routes, "get_verdict", fake_get_verdict)

    # fetch_all_verdicts() now returns {"verdicts": {...}, "count": N, "cached": bool}
    result = l12_routes.fetch_all_verdicts()

    verdicts = result["verdicts"]
    assert "GBPJPY" in verdicts
    assert verdicts["GBPJPY"]["symbol"] == "GBPJPY"
    assert verdicts["GBPJPY"]["verdict"] == "HOLD"
    assert verdicts["GBPJPY"]["_meta"]["cache_ttl_seconds"] == l12_routes.VERDICT_TTL_SEC


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


def test_build_pipeline_data_unexecuted_layers_marked_skip() -> None:
    """Layers not in execution_map.layers_executed must be marked 'skip'."""
    verdict_data = {
        "verdict": "EXECUTE",
        "confidence": 0.88,
        "gates": {"passed": 9, "total": 9},
        "execution_map": {
            "pair": "EURUSD",
            "constitutional_verdict": "EXECUTE",
            "halt_reason": None,
            "layers_executed": ["L1", "L2", "L3", "L12"],
            "engines_invoked": [],
        },
    }
    pipeline = l12_routes._build_pipeline_data("EURUSD", verdict_data)
    layer_statuses = {lyr["id"]: lyr["status"] for lyr in pipeline["layers"]}

    # Executed layers should be pass/fail (not skip)
    assert layer_statuses["L1"] == "pass"
    assert layer_statuses["L2"] == "pass"

    # L4, L5, L6, etc. were NOT executed — should be 'skip'
    assert layer_statuses["L4"] == "skip"
    assert layer_statuses["L5"] == "skip"
    assert layer_statuses["L9"] == "skip"


def test_build_pipeline_data_no_execution_map_defaults_to_pass() -> None:
    """When execution_map is absent all non-L12 layers default to 'pass'."""
    verdict_data = {
        "verdict": "HOLD",
        "confidence": 0.4,
        "gates": {"passed": 6, "total": 9},
    }
    pipeline = l12_routes._build_pipeline_data("GBPUSD", verdict_data)
    for layer in pipeline["layers"]:
        if layer["id"] != "L12":
            # Without execution_map, layers_executed_set is empty so no layer is marked "skip".
            # Without gate results, gated layers fall back to "pass".
            assert layer["status"] == "pass", f"Expected 'pass' for {layer['id']} without execution_map, got {layer['status']!r}"
