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
