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
        return {"symbol": pair, "verdict": "HOLD"} if pair == "GBPJPY" else None

    monkeypatch.setattr(l12_routes, "get_verdict", fake_get_verdict)

    verdicts = l12_routes.fetch_all_verdicts()

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
    monkeypatch.setattr(l12_routes, "LiveContextBus", lambda: _FakeBus())
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
    monkeypatch.setattr(l12_routes, "LiveContextBus", lambda: _FakeBus())

    payload = l12_routes.fetch_internal_verdict_path(pair="EURUSD")
    row = payload["pairs"][0]

    assert payload["redis_ok"] is False
    assert payload["redis_error"] == "redis unavailable"
    assert row["pair"] == "EURUSD"
    assert row["redis_key_exists"] is False
    assert row["warmup_status"]["ready"] is False
