"""P1B: pipeline shadow preview is flag-guarded, isolated, and never live."""

from __future__ import annotations

import logging
from importlib import import_module


def _pipeline_cls():
    return getattr(import_module("pipeline.wolf_constitutional_pipeline"), "WolfConstitutionalPipeline")


def _bare_pipeline():
    # Bypass the heavy __init__; the shadow hook only touches _shadow_active_directions.
    cls = _pipeline_cls()
    pipe = cls.__new__(cls)
    pipe._shadow_active_directions = {}
    return pipe


def _counter_payload():
    return {
        "symbol": "USDCAD",
        "validated_direction": "SELL",
        "status": "SELL_ABSORPTION_WATCH",
        "phase_priced": "EXHAUSTION_AT_RESISTANCE",
        "valid_for_execution": False,
    }


def test_shadow_preview_off_by_default_no_line(caplog):
    pipe = _bare_pipeline()
    pipe._shadow_active_directions["USDCAD"] = "BUY"
    caplog.set_level(logging.WARNING, logger="signal_json")

    pipe._emit_lifecycle_shadow_preview(_counter_payload())

    assert "[SignalLifecycleShadowPreview]" not in caplog.text


def test_shadow_preview_on_emits_isolated_line(monkeypatch, caplog):
    monkeypatch.setenv("SIGNAL_LIFECYCLE_MANAGER_SHADOW_ENABLED", "true")
    pipe = _bare_pipeline()
    pipe._shadow_active_directions["USDCAD"] = "BUY"
    caplog.set_level(logging.WARNING, logger="signal_json")

    pipe._emit_lifecycle_shadow_preview(_counter_payload())

    text = caplog.text
    assert "[SignalLifecycleShadowPreview]" in text
    assert '"live_applied":false' in text
    assert '"suggested_lifecycle_status":"ACTIVE_BUY_PROTECT_PROFIT"' in text


def test_shadow_preview_on_without_active_signal_no_line(monkeypatch, caplog):
    monkeypatch.setenv("SIGNAL_LIFECYCLE_MANAGER_SHADOW_ENABLED", "true")
    pipe = _bare_pipeline()  # no active signal recorded
    caplog.set_level(logging.WARNING, logger="signal_json")

    pipe._emit_lifecycle_shadow_preview(_counter_payload())

    assert "[SignalLifecycleShadowPreview]" not in caplog.text


def test_shadow_records_execution_grade_final_then_previews_counter(monkeypatch, caplog):
    monkeypatch.setenv("SIGNAL_LIFECYCLE_MANAGER_SHADOW_ENABLED", "true")
    pipe = _bare_pipeline()
    caplog.set_level(logging.WARNING, logger="signal_json")

    # An execution-grade BUY final is recorded but does not preview itself.
    final = {"symbol": "USDCAD", "status": "BUY_TIMING_VALID", "final_direction": "BUY", "valid_for_execution": True}
    pipe._emit_lifecycle_shadow_preview(final)
    assert "[SignalLifecycleShadowPreview]" not in caplog.text
    assert pipe._shadow_active_directions["USDCAD"] == "BUY"

    # A subsequent SELL counter against the active BUY produces a preview.
    pipe._emit_lifecycle_shadow_preview(_counter_payload())
    assert "[SignalLifecycleShadowPreview]" in caplog.text
