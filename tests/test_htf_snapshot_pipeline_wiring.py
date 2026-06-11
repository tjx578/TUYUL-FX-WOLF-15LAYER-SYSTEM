"""Increment H1 — pipeline wiring for the HTF Structure Snapshot.

Verifies the flag-guarded, per-symbol-deduped, non-executable emit hook
(`WolfConstitutionalPipeline._emit_htf_structure_snapshot`). Mirrors the
construction style of ``test_microboost_watch_diagnostic.py`` (build the
pipeline via ``__new__`` and inject only the state the method touches).
"""

from __future__ import annotations

import logging

from analysis.htf_structure_snapshot import HTFStructureSnapshotResolver
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

_FLAG = "HTF_STRUCTURE_SNAPSHOT_ENABLED"


def _c(high: float, low: float, close: float | None = None) -> dict[str, float]:
    close = close if close is not None else (high + low) / 2
    return {"open": close, "high": high, "low": low, "close": close}


def _zigzag(pivots: list[float], eps: float = 0.15, fill: int = 2) -> list[dict[str, float]]:
    closes: list[float] = []
    prev = pivots[0]
    for level in pivots:
        for s in range(1, fill + 1):
            closes.append(prev + (level - prev) * s / (fill + 1))
        closes.append(level)
        prev = level
    return [_c(x + eps, x - eps, x) for x in closes]


def _bearish(base: float = 1.62) -> list[dict[str, float]]:
    highs = [base - i * 0.02 for i in range(4)]
    lows = [base - 0.06 - i * 0.02 for i in range(4)]
    pivots: list[float] = []
    for hi, lo in zip(highs, lows, strict=False):
        pivots.extend((hi, lo))
    return _zigzag(pivots)


class _FakeBus:
    def __init__(self, data: dict[str, list[dict[str, float]]]):
        self._data = data

    def get_candle_history(self, symbol, timeframe, count=None):
        rows = self._data.get(f"{symbol}:{timeframe}", [])
        if count is not None and count < len(rows):
            return rows[-count:]
        return rows


def _pipeline_with_source(data: dict[str, list[dict[str, float]]]) -> WolfConstitutionalPipeline:
    p = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    p._htf_snapshot_resolver = HTFStructureSnapshotResolver(candle_source=_FakeBus(data))
    p._last_htf_snapshot_key = {}
    return p


def _bearish_data() -> dict[str, list[dict[str, float]]]:
    return {"GBPNZD:D1": _bearish(1.62), "GBPNZD:H4": _bearish(1.34)}


def test_flag_off_no_emit(monkeypatch, caplog):
    monkeypatch.delenv(_FLAG, raising=False)
    p = _pipeline_with_source(_bearish_data())
    with caplog.at_level(logging.WARNING):
        p._emit_htf_structure_snapshot("GBPNZD")
    assert "[HTFStructureSnapshot]" not in caplog.text


def test_flag_on_emits_non_executable_snapshot(monkeypatch, caplog):
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline_with_source(_bearish_data())
    with caplog.at_level(logging.WARNING):
        p._emit_htf_structure_snapshot("GBPNZD")
    assert "[HTFStructureSnapshot]" in caplog.text
    assert '"event":"htf_structure_snapshot_json"' in caplog.text
    assert '"daily_bias":"BEARISH"' in caplog.text
    # BUY pressure is never an auto BUY LIMIT — it must be in the blocked list.
    assert '"BUY_LIMIT"' in caplog.text
    assert '"valid_for_execution":false' in caplog.text
    assert '"is_final_signal":false' in caplog.text


def test_per_symbol_dedup_suppresses_unchanged_repeat(monkeypatch, caplog):
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline_with_source(_bearish_data())
    with caplog.at_level(logging.WARNING):
        p._emit_htf_structure_snapshot("GBPNZD")
        p._emit_htf_structure_snapshot("GBPNZD")  # identical structure -> suppressed
    assert caplog.text.count("[HTFStructureSnapshot]") == 1


def test_resolve_failure_is_swallowed(monkeypatch, caplog):
    monkeypatch.setenv(_FLAG, "true")

    class _BoomResolver:
        def resolve(self, _symbol):
            raise RuntimeError("boom")

    p = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    p._htf_snapshot_resolver = _BoomResolver()
    p._last_htf_snapshot_key = {}
    # Must not raise — observability must never disturb the execution path.
    with caplog.at_level(logging.WARNING):
        p._emit_htf_structure_snapshot("GBPNZD")
    assert "[HTFStructureSnapshot]" not in caplog.text
