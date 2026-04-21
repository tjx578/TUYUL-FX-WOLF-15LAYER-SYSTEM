"""Tests for scripts/analyze_shadow_journal.py and metrics wiring."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# Import the analyze module by file path so it works without packaging.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
analyze_shadow_journal = importlib.import_module("analyze_shadow_journal")

from contracts.shadow_hook import (  # noqa: E402
    begin_shadow_session,
    finalize_shadow_session,
    set_sink,
)
from contracts.shadow_sink import ShadowJournalSink  # noqa: E402

FLAG = "WOLF_SHADOW_CAPTURE_ENABLED"


def _legacy(layer: str, status: str = "PASS", blockers: list[str] | None = None) -> dict[str, Any]:
    return {
        "layer": layer,
        "layer_version": "1.0.0",
        "timestamp": "2026-04-21T12:00:00+00:00",
        "input_ref": f"EURUSD_{layer}",
        "status": status,
        "continuation_allowed": status in ("PASS", "WARN"),
        "blocker_codes": blockers or [],
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


def _populate(path: Path, n: int = 3, include_blocker: bool = False) -> None:
    sink = ShadowJournalSink(path=path)
    for i in range(n):
        sess = begin_shadow_session(symbol="EURUSD", signal_id=f"sid-{i:03d}")
        assert sess is not None
        phase1 = SimpleNamespace(
            l1=_legacy("L1"),
            l2=_legacy("L2"),
            l3=_legacy("L3"),
        )
        sess.ingest_chain_result(phase1)
        if include_blocker and i == 1:
            sess.capture(_legacy("L6", status="FAIL", blockers=["RISK_CEILING"]))
        set_sink(sink)  # ensure hook writes into this sink
        finalize_shadow_session(sess)


# ─────────────────────────────────────────────────────────────────────────
# analyze() pure function
# ─────────────────────────────────────────────────────────────────────────


class TestAnalyzeFn:
    def test_empty_iterable(self):
        r = analyze_shadow_journal.analyze([])
        assert r["total_records"] == 0
        assert r["symbols"] == {}
        assert r["envelope_counts"] == {}
        assert r["integrity_issues"] == []

    def test_counts_and_time_range(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        path = tmp_path / "shadow.jsonl"
        _populate(path, n=3)
        records = list(analyze_shadow_journal._iter_records(path))
        assert len(records) == 3

        r = analyze_shadow_journal.analyze(records)
        assert r["total_records"] == 3
        assert r["symbols"] == {"EURUSD": 3}
        assert r["envelope_counts"]["min"] == 3
        assert r["envelope_counts"]["max"] == 3
        assert r["projection_failure_rate"] == 0.0
        assert r["bundle_build"] == {"ok": 3, "failed": 0}
        assert r["time_range"]["first"] is not None
        assert r["time_range"]["last"] is not None

    def test_plane_distribution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        path = tmp_path / "shadow.jsonl"
        _populate(path, n=2)
        records = list(analyze_shadow_journal._iter_records(path))
        r = analyze_shadow_journal.analyze(records)
        # Each session ingests L1→context, L2+L3→alpha.
        assert r["plane_envelope_counts"]["context_evidence"] == 2
        assert r["plane_envelope_counts"]["alpha_evidence"] == 4

    def test_hard_blockers_surfaced(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        path = tmp_path / "shadow.jsonl"
        _populate(path, n=3, include_blocker=True)
        records = list(analyze_shadow_journal._iter_records(path))
        r = analyze_shadow_journal.analyze(records)
        assert r["hard_blockers_top"].get("RISK_CEILING") == 1

    def test_malformed_lines_are_skipped(self, tmp_path: Path):
        path = tmp_path / "shadow.jsonl"
        path.write_text(
            '{"recorded_at":"2026-04-21T10:00:00Z","summary":{"symbol":"EURUSD","envelope_count":0,"failure_count":0,"build_diagnostics":[]},"bundle":null}\n'
            "this is not json\n"
            "\n"
            '{"recorded_at":"2026-04-21T10:05:00Z","summary":{"symbol":"GBPUSD","envelope_count":1,"failure_count":0,"build_diagnostics":[]},"bundle":null}\n',
            encoding="utf-8",
        )
        records = list(analyze_shadow_journal._iter_records(path))
        assert len(records) == 2
        r = analyze_shadow_journal.analyze(records)
        assert r["total_records"] == 2
        assert set(r["symbols"].keys()) == {"EURUSD", "GBPUSD"}

    def test_integrity_detects_v11_leak(self):
        """A bundle that wrongly contains V11 envelope should surface an issue."""
        fake_record = {
            "recorded_at": "2026-04-21T10:00:00Z",
            "summary": {
                "signal_id": "sid-x",
                "symbol": "EURUSD",
                "envelope_count": 1,
                "failure_count": 0,
                "build_diagnostics": [],
            },
            "bundle": {
                "signal_id": "sid-x",
                "symbol": "EURUSD",
                "hard_blockers": [],
                "alpha_evidence": [{"layer_id": "V11", "evidence_plane": "alpha"}],
            },
        }
        r = analyze_shadow_journal.analyze([fake_record])
        assert any("V11" in msg for msg in r["integrity_issues"])

    def test_integrity_detects_signal_id_mismatch(self):
        fake_record = {
            "recorded_at": "2026-04-21T10:00:00Z",
            "summary": {
                "signal_id": "sid-a",
                "symbol": "EURUSD",
                "envelope_count": 0,
                "failure_count": 0,
                "build_diagnostics": [],
            },
            "bundle": {"signal_id": "sid-b"},
        }
        r = analyze_shadow_journal.analyze([fake_record])
        assert any("signal_id mismatch" in msg for msg in r["integrity_issues"])


# ─────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────


class TestCLI:
    def test_missing_file_returns_1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        rc = analyze_shadow_journal.main(["--path", str(tmp_path / "nope.jsonl")])
        assert rc == 1
        assert "not found" in capsys.readouterr().err.lower()

    def test_text_output_zero_rc_on_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        monkeypatch.setenv(FLAG, "1")
        path = tmp_path / "shadow.jsonl"
        _populate(path, n=2)
        rc = analyze_shadow_journal.main(["--path", str(path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "SHADOW JOURNAL ANALYSIS" in out
        assert "EURUSD" in out
        assert "Integrity" in out

    def test_json_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
        monkeypatch.setenv(FLAG, "1")
        path = tmp_path / "shadow.jsonl"
        _populate(path, n=1)
        rc = analyze_shadow_journal.main(["--path", str(path), "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["total_records"] == 1
        assert "envelope_counts" in data

    def test_integrity_issue_rc_is_2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        path = tmp_path / "shadow.jsonl"
        # Hand-craft a V11-leak record.
        rec = {
            "recorded_at": "2026-04-21T10:00:00Z",
            "summary": {
                "signal_id": "sid-x",
                "symbol": "EURUSD",
                "envelope_count": 1,
                "failure_count": 0,
                "build_diagnostics": [],
            },
            "bundle": {
                "signal_id": "sid-x",
                "symbol": "EURUSD",
                "hard_blockers": [],
                "alpha_evidence": [{"layer_id": "V11", "evidence_plane": "alpha"}],
            },
        }
        path.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        rc = analyze_shadow_journal.main(["--path", str(path)])
        assert rc == 2
        out = capsys.readouterr().out
        assert "INTEGRITY ISSUES" in out


# ─────────────────────────────────────────────────────────────────────────
# Metrics wiring — best effort, must not break hook
# ─────────────────────────────────────────────────────────────────────────


class TestMetricsWiring:
    def test_metrics_module_exposes_shadow_counters(self):
        import core.metrics as m

        assert hasattr(m, "SHADOW_CAPTURE_WRITES_TOTAL")
        assert hasattr(m, "SHADOW_CAPTURE_ENVELOPES_TOTAL")
        assert hasattr(m, "SHADOW_CAPTURE_FAILURES_TOTAL")

    def test_finalize_bumps_counters_without_raising(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(FLAG, "1")
        sink_path = tmp_path / "shadow.jsonl"
        set_sink(ShadowJournalSink(path=sink_path))
        sess = begin_shadow_session(symbol="EURUSD")
        assert sess is not None
        sess.capture(_legacy("L1"))
        # Must not raise even though metrics counters are exercised.
        result = finalize_shadow_session(sess)
        assert result is not None
        assert sink_path.exists()
