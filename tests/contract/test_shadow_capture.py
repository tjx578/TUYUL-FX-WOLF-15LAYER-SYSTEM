"""Tests for contracts.shadow_capture — P1-A.5 opt-in runtime wiring."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from contracts.decision_bundle import DecisionBundle
from contracts.layer_envelope import LayerEnvelope
from contracts.shadow_capture import ShadowCaptureSession

SIGNAL_ID = "sig_p1a5_shadow"
SYMBOL = "EURUSD"
TIMEFRAME = "H1"
RUNTIME_CTX = "stream:runtime:EURUSD:seq:42"


def _legacy(layer: str, status: str = "PASS", blockers: list[str] | None = None) -> dict:
    return {
        "layer": layer,
        "layer_version": "1.0.0",
        "timestamp": "2026-04-21T12:00:00+00:00",
        "input_ref": f"{SYMBOL}_{layer}_run",
        "status": status,
        "continuation_allowed": status in ("PASS", "WARN"),
        "blocker_codes": blockers or [],
        "warning_codes": [],
        "fallback_class": "NO_FALLBACK",
        "freshness_state": "FRESH",
        "warmup_state": "READY",
        "coherence_band": "HIGH",
        "coherence_score": 0.8,
        "features": {"aligned": True},
        "routing": {"next_legal_targets": []},
        "audit": {"rule_hits": [], "notes": []},
    }


def _session() -> ShadowCaptureSession:
    return ShadowCaptureSession(
        signal_id=SIGNAL_ID,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        runtime_context_ref=RUNTIME_CTX,
    )


# ─────────────────────────────────────────────────────────────────────────
# Construction / identity
# ─────────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_basic_construction(self):
        s = _session()
        assert s.signal_id == SIGNAL_ID
        assert s.symbol == SYMBOL
        assert s.timeframe == TIMEFRAME
        assert s.runtime_context_ref == RUNTIME_CTX
        assert s.envelopes() == []
        assert s.failures() == []

    def test_empty_timeframe_rejected(self):
        with pytest.raises(ValueError):
            ShadowCaptureSession(
                signal_id=SIGNAL_ID,
                symbol=SYMBOL,
                timeframe="",
                runtime_context_ref=RUNTIME_CTX,
            )

    def test_empty_runtime_context_ref_rejected(self):
        with pytest.raises(ValueError):
            ShadowCaptureSession(
                signal_id=SIGNAL_ID,
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                runtime_context_ref="",
            )

    def test_empty_signal_id_rejected(self):
        # Propagated via EnvelopeCollection.
        with pytest.raises(ValueError):
            ShadowCaptureSession(
                signal_id="",
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                runtime_context_ref=RUNTIME_CTX,
            )


# ─────────────────────────────────────────────────────────────────────────
# capture() — per-layer passthrough
# ─────────────────────────────────────────────────────────────────────────


class TestCapture:
    def test_capture_returns_envelope(self):
        s = _session()
        env = s.capture(_legacy("L2"))
        assert isinstance(env, LayerEnvelope)
        assert env.layer_id == "L2"
        assert len(s.envelopes()) == 1

    def test_capture_account_state_leak_returns_none_and_records_failure(self):
        s = _session()
        leaky = _legacy("L6")
        leaky["features"]["equity"] = 1000.0
        env = s.capture(leaky)
        assert env is None
        assert len(s.envelopes()) == 0
        assert len(s.failures()) == 1

    def test_capture_many_pairs(self):
        s = _session()
        out = s.capture_many([("L1", _legacy("L1")), ("L2", _legacy("L2"))])
        assert all(isinstance(e, LayerEnvelope) for e in out)
        assert {e.layer_id for e in s.envelopes()} == {"L1", "L2"}


# ─────────────────────────────────────────────────────────────────────────
# ingest_chain_result — primary pipeline hook
# ─────────────────────────────────────────────────────────────────────────


class TestIngestChainResult:
    def test_ingests_from_chainresult_like_object(self):
        s = _session()
        chain = SimpleNamespace(
            l1=_legacy("L1"),
            l2=_legacy("L2"),
            l3=_legacy("L3"),
        )
        s.ingest_chain_result(chain)
        layers = {env.layer_id for env in s.envelopes()}
        assert layers == {"L1", "L2", "L3"}

    def test_ingests_from_chainresult_to_dict(self):
        s = _session()
        chain_dict = {
            "phase": "PHASE_1",
            "status": "PASS",
            "l1": _legacy("L1"),
            "l2": _legacy("L2"),
            "l3": _legacy("L3"),
        }
        s.ingest_chain_result(chain_dict)
        assert {env.layer_id for env in s.envelopes()} == {"L1", "L2", "L3"}

    def test_missing_layer_is_skipped_silently(self):
        """Chain that never reached L3 → shadow session captures only L1+L2."""
        s = _session()
        chain = SimpleNamespace(l1=_legacy("L1"), l2=_legacy("L2"), l3={})
        s.ingest_chain_result(chain)
        assert {env.layer_id for env in s.envelopes()} == {"L1", "L2"}

    def test_none_chain_result_does_not_raise(self):
        s = _session()
        s.ingest_chain_result(None)
        assert s.envelopes() == []

    def test_legacy_result_exception_does_not_break_pipeline(self):
        """The whole P1-A.5 safety contract: bad input → failure log, no raise."""
        s = _session()
        bad = _legacy("L2")
        bad["features"]["balance"] = 100.0
        chain = SimpleNamespace(l1=_legacy("L1"), l2=bad, l3=_legacy("L3"))
        s.ingest_chain_result(chain)  # must not raise
        assert {env.layer_id for env in s.envelopes()} == {"L1", "L3"}
        assert len(s.failures()) == 1
        assert s.failures()[0].layer_id == "L2"


# ─────────────────────────────────────────────────────────────────────────
# try_build — shadow bundle construction
# ─────────────────────────────────────────────────────────────────────────


class TestTryBuild:
    def test_try_build_on_empty_session_succeeds(self):
        s = _session()
        bundle, diag = s.try_build()
        assert isinstance(bundle, DecisionBundle)
        assert diag is None
        assert bundle.all_envelopes() == []

    def test_try_build_after_ingest(self):
        s = _session()
        chain = SimpleNamespace(l1=_legacy("L1"), l2=_legacy("L2"), l3=_legacy("L3"))
        s.ingest_chain_result(chain)
        s.capture(_legacy("L6"))
        s.capture(_legacy("L11"))
        bundle, diag = s.try_build()
        assert diag is None
        assert bundle is not None
        assert {e.layer_id for e in bundle.context_evidence} == {"L1"}
        assert {e.layer_id for e in bundle.alpha_evidence} == {"L2", "L3"}
        assert {e.layer_id for e in bundle.risk_evidence} == {"L6"}
        assert {e.layer_id for e in bundle.economics_evidence} == {"L11"}

    def test_v11_ingested_but_excluded_from_bundle(self):
        s = _session()
        s.capture(_legacy("V11"))
        bundle, diag = s.try_build()
        assert diag is None
        assert bundle is not None
        assert bundle.all_envelopes() == []  # V11 filtered out
        assert "V11" in s.collection  # still retained for audit

    def test_hard_blockers_propagate_to_bundle(self):
        s = _session()
        s.capture(_legacy("L6", status="FAIL", blockers=["RISK_CEILING"]))
        bundle, diag = s.try_build()
        assert diag is None
        assert bundle is not None
        assert "RISK_CEILING" in bundle.hard_blockers()
        assert s.hard_blockers() == ["RISK_CEILING"]


# ─────────────────────────────────────────────────────────────────────────
# Summary / audit
# ─────────────────────────────────────────────────────────────────────────


class TestSummary:
    def test_summary_carries_session_metadata(self):
        s = _session()
        s.capture(_legacy("L1"))
        summary = s.summary()
        assert summary["signal_id"] == SIGNAL_ID
        assert summary["symbol"] == SYMBOL
        assert summary["timeframe"] == TIMEFRAME
        assert summary["runtime_context_ref"] == RUNTIME_CTX
        assert summary["envelope_count"] == 1
        assert summary["build_diagnostics"] == []

    def test_failed_build_adds_diagnostic_entry(self):
        """Force a build failure by constructing with an illegal timeframe."""
        bad = ShadowCaptureSession(
            signal_id=SIGNAL_ID,
            symbol=SYMBOL,
            timeframe="X",  # DecisionBundle requires min_length=2 → will fail
            runtime_context_ref=RUNTIME_CTX,
        )
        bundle, diag = bad.try_build()
        assert bundle is None
        assert diag is not None
        summary = bad.summary()
        assert len(summary["build_diagnostics"]) == 1
        assert summary["build_diagnostics"][0]["signal_id"] == SIGNAL_ID


# ─────────────────────────────────────────────────────────────────────────
# No authority drift
# ─────────────────────────────────────────────────────────────────────────


class TestNoAuthorityDrift:
    def test_session_never_produces_buy_sell_verdict(self):
        s = _session()
        s.capture(_legacy("L2"), direction="BUY")  # advisory direction on alpha
        bundle, _ = s.try_build()
        assert bundle is not None
        # Bundle has no verdict/direction fields and session has no decide method.
        assert not hasattr(bundle, "verdict")
        assert not hasattr(bundle, "direction")
        assert not hasattr(s, "decide")
        # Advisory direction preserved on the envelope, never elevated.
        assert bundle.alpha_evidence[0].direction == "BUY"

    def test_session_does_not_expose_mutation_on_collection(self):
        """Collection is exposed read-only; callers must use capture()."""
        s = _session()
        coll = s.collection
        # Append-only via dual_emit; direct double-add of same layer raises.
        s.capture(_legacy("L1"))
        assert len(coll) == 1
        # Capturing same layer again is isolated by dual_emit → failure recorded.
        s.capture(_legacy("L1"))
        assert len(coll) == 1
        assert len(s.failures()) == 1
