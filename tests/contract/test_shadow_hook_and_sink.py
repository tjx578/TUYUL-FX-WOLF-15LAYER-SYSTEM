"""Tests for contracts.shadow_sink + contracts.shadow_hook — P1 live wiring."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from contracts.shadow_capture import ShadowCaptureSession
from contracts.shadow_hook import (
    begin_shadow_session,
    finalize_shadow_session,
    is_enabled,
    set_sink,
)
from contracts.shadow_sink import ShadowJournalSink

FLAG = "WOLF_SHADOW_CAPTURE_ENABLED"


def _legacy(layer: str, status: str = "PASS") -> dict[str, Any]:
    return {
        "layer": layer,
        "layer_version": "1.0.0",
        "timestamp": "2026-04-21T12:00:00+00:00",
        "input_ref": f"EURUSD_{layer}",
        "status": status,
        "continuation_allowed": status in ("PASS", "WARN"),
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
def _reset_flag_and_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.delenv("WOLF_SHADOW_JOURNAL_PATH", raising=False)
    set_sink(None)
    # Reset one-shot init log so each test can verify it independently.
    import contracts.shadow_hook as _sh  # noqa: PLC0415

    _sh._INIT_LOGGED = False


# ─────────────────────────────────────────────────────────────────────────
# Sink — write path
# ─────────────────────────────────────────────────────────────────────────


class TestSinkWrite:
    def test_writes_record_to_jsonl(self, tmp_path: Path):
        path = tmp_path / "shadow.jsonl"
        sink = ShadowJournalSink(path=path)
        sess = ShadowCaptureSession(
            signal_id="sid-001",
            symbol="EURUSD",
            timeframe="H1",
            runtime_context_ref="test-ctx",
        )
        sess.capture(_legacy("L1"))
        bundle, _ = sess.try_build()
        ok = sink.record(sess.summary(), bundle)
        assert ok is True
        assert sink.write_count == 1
        assert path.exists()
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert len(records) == 1
        r = records[0]
        assert "recorded_at" in r
        assert r["summary"]["signal_id"] == "sid-001"
        assert r["bundle"] is not None
        assert r["bundle"]["signal_id"] == "sid-001"

    def test_appends_multiple_records(self, tmp_path: Path):
        path = tmp_path / "shadow.jsonl"
        sink = ShadowJournalSink(path=path)
        for i in range(3):
            sess = ShadowCaptureSession(
                signal_id=f"sid-{i:03d}",
                symbol="EURUSD",
                timeframe="H1",
                runtime_context_ref=f"ctx-{i}",
            )
            bundle, _ = sess.try_build()
            sink.record(sess.summary(), bundle)
        lines = path.read_text().splitlines()
        assert len(lines) == 3
        assert sink.write_count == 3

    def test_none_bundle_is_recorded_as_null(self, tmp_path: Path):
        path = tmp_path / "shadow.jsonl"
        sink = ShadowJournalSink(path=path)
        ok = sink.record({"signal_id": "sid-nb", "symbol": "EURUSD"}, None)
        assert ok is True
        record = json.loads(path.read_text().splitlines()[0])
        assert record["bundle"] is None

    def test_write_failure_never_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Point sink at a path whose parent cannot be created (file in the way).
        blocker = tmp_path / "blocker"
        blocker.write_text("")
        path = blocker / "shadow.jsonl"  # parent "blocker" is a file, not a dir
        sink = ShadowJournalSink(path=path)
        ok = sink.record({"signal_id": "sid-x", "symbol": "EURUSD"}, None)
        assert ok is False
        assert sink.error_count == 1

    def test_env_overrides_default_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        target = tmp_path / "env_path.jsonl"
        monkeypatch.setenv("WOLF_SHADOW_JOURNAL_PATH", str(target))
        sink = ShadowJournalSink()
        assert sink.path == target


# ─────────────────────────────────────────────────────────────────────────
# Hook — feature flag gating
# ─────────────────────────────────────────────────────────────────────────


class TestFlagGating:
    def test_flag_off_by_default(self):
        assert is_enabled() is False

    def test_flag_on_via_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        assert is_enabled() is True

    @pytest.mark.parametrize("val", ["true", "TRUE", "True", "yes", "on"])
    def test_flag_truthy_variants(self, monkeypatch: pytest.MonkeyPatch, val: str):
        monkeypatch.setenv(FLAG, val)
        assert is_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "", "random"])
    def test_flag_falsy_variants(self, monkeypatch: pytest.MonkeyPatch, val: str):
        monkeypatch.setenv(FLAG, val)
        assert is_enabled() is False


# ─────────────────────────────────────────────────────────────────────────
# Hook — begin_shadow_session
# ─────────────────────────────────────────────────────────────────────────


class TestBeginSession:
    def test_returns_none_when_flag_off(self):
        assert begin_shadow_session(symbol="EURUSD") is None

    def test_returns_session_when_flag_on(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        sess = begin_shadow_session(symbol="EURUSD", signal_id="sid-hook-1")
        assert isinstance(sess, ShadowCaptureSession)
        assert sess.symbol == "EURUSD"
        assert sess.signal_id == "sid-hook-1"
        assert sess.timeframe == "H1"
        assert sess.runtime_context_ref.startswith("runtime:EURUSD:sid-hook-1")

    def test_auto_generates_signal_id(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        sess = begin_shadow_session(symbol="EURUSD")
        assert isinstance(sess, ShadowCaptureSession)
        assert sess.signal_id.startswith("shadow-")

    def test_accepts_custom_timeframe(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        sess = begin_shadow_session(symbol="EURUSD", timeframe="H4")
        assert sess is not None
        assert sess.timeframe == "H4"

    def test_returns_none_on_invalid_input(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        # Empty symbol — EnvelopeCollection will reject; hook must swallow.
        assert begin_shadow_session(symbol="") is None


# ─────────────────────────────────────────────────────────────────────────
# Hook — finalize_shadow_session
# ─────────────────────────────────────────────────────────────────────────


class TestFinalizeSession:
    def test_noop_on_none_session(self, tmp_path: Path):
        # Flag off → session None → no file written.
        sink_path = tmp_path / "shadow.jsonl"
        set_sink(ShadowJournalSink(path=sink_path))
        result = finalize_shadow_session(None)
        assert result is None
        assert not sink_path.exists()

    def test_writes_record_when_session_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        sink_path = tmp_path / "shadow.jsonl"
        set_sink(ShadowJournalSink(path=sink_path))

        sess = begin_shadow_session(symbol="EURUSD", signal_id="sid-fin-1")
        assert sess is not None
        sess.ingest_chain_result(SimpleNamespace(l1=_legacy("L1"), l2=_legacy("L2"), l3=_legacy("L3")))

        summary = finalize_shadow_session(sess)
        assert summary is not None
        assert summary["signal_id"] == "sid-fin-1"
        assert sink_path.exists()
        records = [json.loads(line) for line in sink_path.read_text().splitlines()]
        assert len(records) == 1
        assert records[0]["summary"]["envelope_count"] == 3

    def test_finalize_never_raises_on_sink_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        blocker = tmp_path / "blocker"
        blocker.write_text("")
        set_sink(ShadowJournalSink(path=blocker / "shadow.jsonl"))
        sess = begin_shadow_session(symbol="EURUSD")
        assert sess is not None
        # No exception must propagate even though sink write will fail.
        result = finalize_shadow_session(sess)
        assert result is not None  # summary computed before sink attempt
        assert result["signal_id"].startswith("shadow-")


# ─────────────────────────────────────────────────────────────────────────
# End-to-end — flag-off path is literal no-op
# ─────────────────────────────────────────────────────────────────────────


class TestFlagOffIsNoop:
    def test_full_cycle_flag_off_writes_nothing(self, tmp_path: Path):
        sink_path = tmp_path / "shadow.jsonl"
        set_sink(ShadowJournalSink(path=sink_path))
        assert FLAG not in os.environ or os.environ[FLAG] not in {"1", "true"}

        sess = begin_shadow_session(symbol="EURUSD")
        assert sess is None
        # Pipeline pattern: session and session.capture(...) -> short-circuits
        _ = sess and sess.capture(_legacy("L1"))
        _ = sess and sess.ingest_chain_result(None)
        finalize_shadow_session(sess)

        assert not sink_path.exists()


# ─────────────────────────────────────────────────────────────────────────
# One-shot init log — operator diagnostic signal
# ─────────────────────────────────────────────────────────────────────────


class TestInitLog:
    def test_init_log_fires_once_when_flag_on(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        monkeypatch.setenv(FLAG, "1")
        set_sink(ShadowJournalSink(path=tmp_path / "shadow.jsonl"))

        with caplog.at_level("INFO", logger="contracts.shadow_hook"):
            s1 = begin_shadow_session(symbol="EURUSD")
            s2 = begin_shadow_session(symbol="GBPUSD")

        assert s1 is not None
        assert s2 is not None
        init_logs = [r for r in caplog.records if "[ShadowHook] enabled=" in r.getMessage()]
        # Must fire exactly once, not per session.
        assert len(init_logs) == 1
        msg = init_logs[0].getMessage()
        assert "enabled=True" in msg
        assert "path=" in msg
        assert "metrics=" in msg

    def test_init_log_does_not_fire_when_flag_off(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        set_sink(ShadowJournalSink(path=tmp_path / "shadow.jsonl"))
        with caplog.at_level("INFO", logger="contracts.shadow_hook"):
            s = begin_shadow_session(symbol="EURUSD")
        assert s is None
        init_logs = [r for r in caplog.records if "[ShadowHook] enabled=" in r.getMessage()]
        assert init_logs == []
