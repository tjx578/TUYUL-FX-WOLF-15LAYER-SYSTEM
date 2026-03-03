from api import l12_routes


def test_fetch_pairs_includes_configured_cross_pair() -> None:
    symbols = {
        pair["symbol"]
        for pair in l12_routes.fetch_pairs()
        if isinstance(pair.get("symbol"), str)
    }
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

    assert verdicts == {"GBPJPY": {"symbol": "GBPJPY", "verdict": "HOLD"}}


def test_build_pipeline_data_marks_unexecuted_layers() -> None:
    payload = {
        "verdict": "HOLD",
        "confidence": "LOW",
        "wolf_status": "NO_HUNT",
        "gates": {"passed": 4, "total": 9},
        "pipeline_execution_map": {
            "pair": "EURUSD",
            "timestamp": "2026-03-03T10:00:00+08:00",
            "layers_executed": ["L0", "L1", "L2", "L3", "L4", "L5"],
            "engines_invoked": ["L1ContextAnalyzer", "L2MTAAnalyzer"],
            "halt_reason": "L6_ANALYZER_NOT_INITIALIZED",
            "constitutional_verdict": "HOLD",
        },
    }

    data = l12_routes._build_pipeline_data("EURUSD", payload)

    # L6 was not executed -> must be visible in heatmap layer state.
    l6 = next(layer for layer in data["layers"] if layer["id"] == "L6")
    assert l6["status"] == "fail"
    assert l6["val"] == "NOT_EXECUTED"
    assert "L6_ANALYZER_NOT_INITIALIZED" in l6["detail"]


def test_fetch_pipeline_execution_map_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        l12_routes,
        "get_verdict",
        lambda _pair: {"timestamp": "2026-03-03T10:00:00+08:00", "verdict": "HOLD"},
    )

    data = l12_routes.fetch_pipeline_execution_map("eurusd")

    assert data["pair"] == "EURUSD"
    assert data["halt_reason"] == "PIPELINE_EXECUTION_MAP_UNAVAILABLE"
    assert data["constitutional_verdict"] == "HOLD"
