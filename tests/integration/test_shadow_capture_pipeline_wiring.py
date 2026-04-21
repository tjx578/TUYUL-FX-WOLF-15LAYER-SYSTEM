"""Integration tests for shadow capture wiring in wolf_constitutional_pipeline.

These verify that the P1 live-wiring patch into
``pipeline/wolf_constitutional_pipeline.py`` is safe:

  - Default (flag off): pipeline import + hook calls are a true no-op.
  - Flag on: hook returns a session, finalize writes to the sink.
  - Source-level assertions: the wiring is present at the documented
    seam (Phase 1 result), so accidental removal triggers a test failure.

We do not instantiate the full pipeline here (it requires heavy
fixtures); we verify the contract at import + source level, and
exercise the hook end-to-end with the same pattern the pipeline uses.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from contracts.shadow_hook import (
    begin_shadow_session,
    finalize_shadow_session,
    set_sink,
)
from contracts.shadow_sink import ShadowJournalSink

FLAG = "WOLF_SHADOW_CAPTURE_ENABLED"
PIPELINE_PATH = Path("pipeline/wolf_constitutional_pipeline.py")


def _legacy(layer: str) -> dict[str, Any]:
    return {
        "layer": layer,
        "layer_version": "1.0.0",
        "timestamp": "2026-04-21T12:00:00+00:00",
        "input_ref": f"EURUSD_{layer}",
        "status": "PASS",
        "continuation_allowed": True,
        "blocker_codes": [],
        "warning_codes": [],
        "fallback_class": "NO_FALLBACK",
        "freshness_state": "FRESH",
        "warmup_state": "READY",
        "coherence_band": "HIGH",
        "coherence_score": 0.8,
        "features": {"ok": True},
        "routing": {"next_legal_targets": []},
        "audit": {"rule_hits": [], "notes": []},
    }


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.delenv("WOLF_SHADOW_JOURNAL_PATH", raising=False)
    set_sink(None)


# ─────────────────────────────────────────────────────────────────────────
# Source-level wiring anchor
# ─────────────────────────────────────────────────────────────────────────


class TestWiringAnchorPresent:
    """Guard rail — fails if someone accidentally removes the wiring."""

    def test_import_present(self):
        src = PIPELINE_PATH.read_text(encoding="utf-8")
        assert "from contracts.shadow_hook import" in src
        assert "begin_shadow_session" in src
        assert "finalize_shadow_session" in src

    def test_wiring_at_phase1_seam(self):
        src = PIPELINE_PATH.read_text(encoding="utf-8")
        # Anchor: wiring must sit immediately adjacent to Phase1 adapter result
        phase1_idx = src.find("_phase1_result = _phase1_adapter.execute(symbol)")
        assert phase1_idx != -1
        window = src[phase1_idx : phase1_idx + 1200]
        assert "begin_shadow_session(symbol=symbol)" in window
        assert "ingest_chain_result(_phase1_result)" in window
        assert "finalize_shadow_session(" in window

    def test_pipeline_module_imports_cleanly(self):
        # Smoke: the wiring import at module level must not break pipeline import.
        # Reload to pick up latest source state.
        mod = importlib.import_module("pipeline.wolf_constitutional_pipeline")
        importlib.reload(mod)
        assert hasattr(mod, "WolfConstitutionalPipeline")


# ─────────────────────────────────────────────────────────────────────────
# Flag-off behavior (default production path)
# ─────────────────────────────────────────────────────────────────────────


class TestFlagOffIsInert:
    def test_begin_returns_none(self):
        assert begin_shadow_session(symbol="EURUSD") is None

    def test_finalize_none_is_noop(self, tmp_path: Path):
        sink_path = tmp_path / "shadow.jsonl"
        set_sink(ShadowJournalSink(path=sink_path))
        finalize_shadow_session(None)
        assert not sink_path.exists()

    def test_full_pattern_flag_off_no_io(self, tmp_path: Path):
        """Mirror the exact pattern wired into the pipeline."""
        sink_path = tmp_path / "shadow.jsonl"
        set_sink(ShadowJournalSink(path=sink_path))

        # --- pipeline pattern ---
        _shadow_session = begin_shadow_session(symbol="EURUSD")
        phase1 = SimpleNamespace(l1=_legacy("L1"), l2=_legacy("L2"), l3=_legacy("L3"))
        if _shadow_session is not None:
            _shadow_session.ingest_chain_result(phase1)
            finalize_shadow_session(_shadow_session)
        # --- end pattern ---

        assert _shadow_session is None
        assert not sink_path.exists()


# ─────────────────────────────────────────────────────────────────────────
# Flag-on behavior (shadow capture engaged)
# ─────────────────────────────────────────────────────────────────────────


class TestFlagOnCaptures:
    def test_full_pattern_flag_on_writes_record(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        sink_path = tmp_path / "shadow.jsonl"
        set_sink(ShadowJournalSink(path=sink_path))

        _shadow_session = begin_shadow_session(symbol="EURUSD")
        phase1 = SimpleNamespace(l1=_legacy("L1"), l2=_legacy("L2"), l3=_legacy("L3"))
        if _shadow_session is not None:
            _shadow_session.ingest_chain_result(phase1)
            finalize_shadow_session(_shadow_session)

        assert _shadow_session is not None
        assert sink_path.exists()
        records = [json.loads(line) for line in sink_path.read_text().splitlines()]
        assert len(records) == 1
        summary = records[0]["summary"]
        assert summary["symbol"] == "EURUSD"
        assert summary["envelope_count"] == 3
        assert summary["failure_count"] == 0

    def test_pattern_isolates_upstream_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """One leaky layer in Phase1 must not break the pipeline pattern."""
        monkeypatch.setenv(FLAG, "1")
        sink_path = tmp_path / "shadow.jsonl"
        set_sink(ShadowJournalSink(path=sink_path))

        leaky = _legacy("L2")
        leaky["features"]["equity"] = 5000.0
        phase1 = SimpleNamespace(l1=_legacy("L1"), l2=leaky, l3=_legacy("L3"))

        _shadow_session = begin_shadow_session(symbol="EURUSD")
        if _shadow_session is not None:
            _shadow_session.ingest_chain_result(phase1)  # MUST NOT raise
            finalize_shadow_session(_shadow_session)

        records = [json.loads(line) for line in sink_path.read_text().splitlines()]
        assert len(records) == 1
        summary = records[0]["summary"]
        assert summary["envelope_count"] == 2  # L1 + L3 only
        assert summary["failure_count"] == 1
