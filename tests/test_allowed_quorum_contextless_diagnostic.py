"""Increment F.1 — Contextless Allowed Quorum Diagnostic Terminal.

The priced ``NO_TRADE_REASONED`` SignalDecisionUpdateJSON already exists and is ON by
default, but it silently returns None when MarketContext / reference price is missing
(``build_signal_json_event`` is price-mandatory and must NOT be weakened). F.1 closes
that silent gap with a DIAGNOSTIC-ONLY event — ``signal_quorum_terminal_diagnostic_json``,
prefix ``[SignalQuorumDiagnosticJSON]`` — emitted straight to the log channel.

Guardrails locked here:
- flag default OFF -> no diagnostic, old behavior
- never emits [SignalDecisionUpdateJSON] / [SignalJSON]; never invents price/entry_zone
- valid_for_execution=false, is_final_signal=false, final_direction=WAIT
- never fires when a watch/signal candidate exists, or under cooldown
- the existing priced NO_TRADE_REASONED path is untouched
"""
from __future__ import annotations

import logging

from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

_FLAG = "SIGNAL_THROTTLE_ALLOWED_QUORUM_CONTEXTLESS_DIAGNOSTIC_ENABLED"
_OUTER_FLAG = "SIGNAL_THROTTLE_ALLOWED_QUORUM_DECISION_UPDATE_ENABLED"


def _pipeline() -> WolfConstitutionalPipeline:
    p = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    p._last_allowed_quorum_decision_at = {}
    return p


def _quorum(**overrides) -> dict:
    q = {"symbol": "GBPCAD", "direction": "BUY", "streak": 2, "quorum_size": 3, "quorum_reached": True}
    q.update(overrides)
    return q


def _apply(p, *, report, market_contexts, source="EXECUTE_REDUCED_RISK_BUY", l12=None):
    p._apply_allowed_quorum_decision_update(
        symbol="GBPCAD",
        synthesis={},
        l12_verdict=l12 if l12 is not None else {},
        report=report,
        market_contexts=market_contexts,
        source_verdict=source,
    )


# --------------------------------------------------------------------------- #
# Unit: _emit_contextless_quorum_diagnostic — payload contract + flag
# --------------------------------------------------------------------------- #


def test_flag_off_no_diagnostic(monkeypatch, caplog):
    """Test #2 — flag OFF: no diagnostic, old behavior."""
    monkeypatch.delenv(_FLAG, raising=False)
    p = _pipeline()
    report: dict = {}
    with caplog.at_level(logging.WARNING):
        out = p._emit_contextless_quorum_diagnostic(
            symbol="GBPCAD", allowed_quorum=_quorum(), l12_verdict={}, report=report
        )
    assert out is None
    assert "[SignalQuorumDiagnosticJSON]" not in caplog.text
    assert "allowed_quorum_contextless_diagnostic" not in report


def test_flag_on_emits_diagnostic_contract(monkeypatch, caplog):
    """Tests #3/#5/#6/#7 — flag ON: emits a diagnostic-only terminal with the right
    contract (no price, no SignalDecisionUpdateJSON prefix, not executable)."""
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline()
    report: dict = {}
    with caplog.at_level(logging.WARNING):
        out = p._emit_contextless_quorum_diagnostic(
            symbol="GBPCAD", allowed_quorum=_quorum(), l12_verdict={}, report=report
        )
    assert out is not None
    assert "[SignalQuorumDiagnosticJSON]" in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text  # #6 not a decision update
    assert "[SignalJSON]" not in caplog.text
    assert out["event"] == "signal_quorum_terminal_diagnostic_json"
    assert out["terminal_status"] == "NO_TRADE_REASONED_CONTEXTLESS"
    assert out["diagnostic_only"] is True
    assert out["valid_for_execution"] is False  # #7
    assert out["is_final_signal"] is False  # #7
    assert out["final_direction"] == "WAIT"  # #7
    # #5 never invents price / entry_zone
    assert "signal_valid_price" not in out
    assert "entry_reference_price" not in out
    assert "entry_zone" not in out
    blockers = out["watch_promotion_blockers"]
    assert {"WATCH_PROMOTION_FAILED", "MARKET_CONTEXT_MISSING", "REFERENCE_PRICE_MISSING"} <= set(blockers)
    assert out["raw_direction"] == "BUY"  # direction reused from quorum, not invented
    assert report["allowed_quorum_contextless_diagnostic"] is out


def test_flag_on_missing_direction_not_invented(monkeypatch, caplog):
    """Direction is preserved from quorum/intel if present, never fabricated."""
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        out = p._emit_contextless_quorum_diagnostic(
            symbol="GBPCAD", allowed_quorum=_quorum(direction=None), l12_verdict={}, report={}
        )
    assert out is not None
    assert out["raw_direction"] is None
    assert out["candidate_direction"] is None
    assert out["final_direction"] == "WAIT"


# --------------------------------------------------------------------------- #
# Integration through _apply_allowed_quorum_decision_update
# --------------------------------------------------------------------------- #


def test_integration_missing_context_emits_diagnostic(monkeypatch, caplog):
    """Tests #3/#4 — quorum reached, no candidate, no market context -> diagnostic."""
    monkeypatch.setenv(_OUTER_FLAG, "true")
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline()
    report = {"allowed_quorum": _quorum()}
    with caplog.at_level(logging.WARNING):
        _apply(p, report=report, market_contexts={})  # empty contexts -> priced payload is None
    assert "[SignalQuorumDiagnosticJSON]" in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text


def test_integration_flag_off_is_silent(monkeypatch, caplog):
    """Test #2 — same conditions, flag OFF -> nothing emitted."""
    monkeypatch.setenv(_OUTER_FLAG, "true")
    monkeypatch.setenv(_FLAG, "false")
    p = _pipeline()
    report = {"allowed_quorum": _quorum()}
    with caplog.at_level(logging.WARNING):
        _apply(p, report=report, market_contexts={})
    assert "[SignalQuorumDiagnosticJSON]" not in caplog.text
    assert "allowed_quorum_contextless_diagnostic" not in report


def test_integration_watch_candidate_blocks_diagnostic(monkeypatch, caplog):
    """Test #8 — if a watch/signal candidate exists, no diagnostic fires."""
    monkeypatch.setenv(_OUTER_FLAG, "true")
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline()
    report = {
        "allowed_quorum": _quorum(),
        "microboost_watch_entry": {"status": "EARLY_SELL_WATCH", "symbol": "GBPCAD"},
    }
    with caplog.at_level(logging.WARNING):
        _apply(p, report=report, market_contexts={})
    assert "[SignalQuorumDiagnosticJSON]" not in caplog.text


def test_integration_priced_path_unchanged(monkeypatch, caplog):
    """Test #1 — when a priced payload CAN be built, the normal path runs and no
    diagnostic is emitted (the existing path is untouched)."""
    monkeypatch.setenv(_OUTER_FLAG, "true")
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline()
    emitted: list[dict] = []
    p._emit_signal_json_payload = lambda payload: emitted.append(payload) or True
    p._allowed_quorum_decision_update_payload = lambda **kwargs: {
        "event": "signal_decision_update_json",
        "status": "NO_TRADE_REASONED",
        "symbol": "GBPCAD",
    }
    report = {"allowed_quorum": _quorum()}
    with caplog.at_level(logging.WARNING):
        _apply(p, report=report, market_contexts={})
    assert emitted  # the normal priced path ran
    assert "[SignalQuorumDiagnosticJSON]" not in caplog.text
    assert report["allowed_quorum_decision_update"]["status"] == "NO_TRADE_REASONED"


def test_integration_cooldown_blocks_second_diagnostic(monkeypatch, caplog):
    """Test #9 — the existing 75s per-symbol cooldown still applies; a second
    application within the window does not re-emit."""
    monkeypatch.setenv(_OUTER_FLAG, "true")
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        _apply(p, report={"allowed_quorum": _quorum()}, market_contexts={})
        _apply(p, report={"allowed_quorum": _quorum()}, market_contexts={})
    assert caplog.text.count("[SignalQuorumDiagnosticJSON]") == 1
