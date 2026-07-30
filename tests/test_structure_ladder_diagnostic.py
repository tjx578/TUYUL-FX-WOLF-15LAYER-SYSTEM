"""Patch A -- StructureLadderDiagnostic (flag-guarded, default OFF, observability-only).

When counter-entry is about to fall back to PROVISIONAL_RR_FALLBACK, emit a read-only
[StructureLadderDiagnostic] that proves whether H4/Daily structure + numeric levels exist.
It must NEVER mutate execution (execution_mutation=false), and must not emit when OFF or when
the target is not a provisional fallback.
"""

from __future__ import annotations

import json
import logging

from analysis.microboost_counter_entry import _maybe_emit_structure_ladder_diagnostic

_FLAG = "STRUCTURE_LADDER_DIAGNOSTIC_ENABLED"
_TAG = "[StructureLadderDiagnostic]"


def _market(**over):
    m = {"price_position": "MAIN_RESISTANCE", "m15_phase": "BEARISH_PULLBACK", "h1_phase": "BULLISH"}
    m.update(over)
    return m


def _payload(caplog):
    line = next(r.message for r in caplog.records if _TAG in r.message)
    return json.loads(line.split(_TAG, 1)[1].strip())


def _emit(market, target_mode="PROVISIONAL_RR_FALLBACK", **extra_tr):
    tr = {"target_mode": target_mode}
    tr.update(extra_tr)
    _maybe_emit_structure_ladder_diagnostic(
        market, symbol="GBPCAD", candidate_direction="SELL", raw_direction="SELL", target_result=tr
    )


def test_off_emits_nothing(monkeypatch, caplog):
    monkeypatch.delenv(_FLAG, raising=False)
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _emit(_market())
    assert _TAG not in caplog.text


def test_on_provisional_emits_diagnostic_no_execution(monkeypatch, caplog):
    monkeypatch.setenv(_FLAG, "true")
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _emit(_market())
    p = _payload(caplog)
    assert p["event"] == "structure_ladder_diagnostic"
    assert p["symbol"] == "GBPCAD"
    assert p["candidate_direction"] == "SELL"
    assert p["execution_mutation"] is False
    assert p["valid_for_execution"] is False
    assert p["final_market_structure_available"] is False
    assert p["fallback_decision"] == "PROVISIONAL_RR_FALLBACK_BLOCKED"
    assert "daily_key_support" in p["missing_required_for_final_market_structure"]
    assert p["numeric_htf_levels"]["daily_key_support"] is None


def test_on_final_market_structure_does_not_emit(monkeypatch, caplog):
    monkeypatch.setenv(_FLAG, "true")
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _emit(_market(), target_mode="FINAL_MARKET_STRUCTURE")
    assert _TAG not in caplog.text


def test_present_fields_are_reported(monkeypatch, caplog):
    monkeypatch.setenv(_FLAG, "true")
    market = _market(major_support=1.85, tp1_support=1.86, support_ladder_ready=True)
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _emit(market)
    p = _payload(caplog)
    assert "major_support" in p["market_context_keys_present"]
    assert "tp1_support" in p["ladder_fields_present"]
    assert p["numeric_htf_levels"]["major_support"] == 1.85
    assert p["missing_required_for_final_market_structure"]  # daily/h4 keys still missing
    assert p["local_refinement_available"]["support_ladder_ready"] is True


def test_does_not_mutate_target_result(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    tr = {"target_mode": "PROVISIONAL_RR_FALLBACK", "valid_for_execution": "UNTOUCHED"}
    before = dict(tr)
    _maybe_emit_structure_ladder_diagnostic(
        _market(), symbol="GBPCAD", candidate_direction="SELL", raw_direction="SELL", target_result=tr
    )
    assert tr == before  # observability-only, no mutation
