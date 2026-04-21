"""P1-C Safety invariants — legacy verdict parity with shadow envelopes.

Parity contract at this stage (pre-runtime-wiring):

  1. Shadow capture MUST NOT mutate the legacy layer dicts it projects.
  2. Shadow capture MUST be deterministic — same input sequence → same
     plane distribution, same blocker set, same envelope order.
  3. Hard blockers present in legacy layer dicts MUST surface in the
     shadow bundle's ``hard_blockers()`` (the set L12 would see).
  4. A leak / rejection in one layer MUST NOT break capture for other
     layers — isolation, not all-or-nothing.
  5. Shadow capture MUST NOT expose any account-state or verdict
     authority on the built bundle, even when legacy dicts are rich.

These are *safety* tests (not contract), because they guard against
runtime regressions once shadow capture is wired into ``app.py``.
"""

from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace
from typing import Any

from contracts.decision_bundle import DecisionBundle
from contracts.layer_envelope import LayerEnvelope
from contracts.shadow_capture import ShadowCaptureSession

SIGNAL_ID = "sig_parity_safety"
SYMBOL = "EURUSD"
TIMEFRAME = "H1"
RUNTIME_CTX = "stream:runtime:EURUSD:parity:0"


def _legacy(
    layer: str,
    status: str = "PASS",
    blockers: list[str] | None = None,
    extra_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = {
        "layer": layer,
        "layer_version": "1.0.0",
        "timestamp": "2026-04-21T12:00:00+00:00",
        "input_ref": f"{SYMBOL}_{layer}_run",
        "status": status,
        "continuation_allowed": status in ("PASS", "WARN"),
        "blocker_codes": list(blockers or []),
        "warning_codes": [],
        "fallback_class": "NO_FALLBACK",
        "freshness_state": "FRESH",
        "warmup_state": "READY",
        "coherence_band": "HIGH",
        "coherence_score": 0.8,
        "features": {"ok": True, **(extra_features or {})},
        "routing": {"next_legal_targets": []},
        "audit": {"rule_hits": [], "notes": []},
    }
    return base


def _fresh_session() -> ShadowCaptureSession:
    return ShadowCaptureSession(
        signal_id=SIGNAL_ID,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        runtime_context_ref=RUNTIME_CTX,
    )


def _hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────
# Invariant 1 — legacy dicts are NEVER mutated
# ─────────────────────────────────────────────────────────────────────────


class TestLegacyDictImmutability:
    def test_capture_does_not_mutate_input(self):
        original = _legacy("L2")
        snapshot = _hash(original)
        sess = _fresh_session()
        sess.capture(original)
        assert _hash(original) == snapshot

    def test_ingest_chain_result_does_not_mutate_chain_dicts(self):
        l1, l2, l3 = _legacy("L1"), _legacy("L2"), _legacy("L3")
        before = (_hash(l1), _hash(l2), _hash(l3))
        sess = _fresh_session()
        sess.ingest_chain_result(SimpleNamespace(l1=l1, l2=l2, l3=l3))
        after = (_hash(l1), _hash(l2), _hash(l3))
        assert before == after

    def test_try_build_does_not_mutate_captured_dicts(self):
        dicts = [_legacy(f"L{i}") for i in (1, 2, 3, 6, 11)]
        frozen = [copy.deepcopy(d) for d in dicts]
        sess = _fresh_session()
        for d in dicts:
            sess.capture(d)
        sess.try_build()
        assert dicts == frozen


# ─────────────────────────────────────────────────────────────────────────
# Invariant 2 — determinism across independent sessions
# ─────────────────────────────────────────────────────────────────────────


class TestDeterminism:
    def _make_and_run(self) -> tuple[DecisionBundle, list[LayerEnvelope]]:
        sess = _fresh_session()
        sess.ingest_chain_result(SimpleNamespace(l1=_legacy("L1"), l2=_legacy("L2"), l3=_legacy("L3")))
        sess.capture(_legacy("L4"))
        sess.capture(_legacy("L6", status="FAIL", blockers=["RISK_CEILING"]))
        sess.capture(_legacy("L11"))
        bundle, _ = sess.try_build()
        assert bundle is not None
        return bundle, sess.envelopes()

    def test_two_sessions_same_input_produce_same_plane_distribution(self):
        b1, _ = self._make_and_run()
        b2, _ = self._make_and_run()
        assert [e.layer_id for e in b1.context_evidence] == [e.layer_id for e in b2.context_evidence]
        assert [e.layer_id for e in b1.alpha_evidence] == [e.layer_id for e in b2.alpha_evidence]
        assert [e.layer_id for e in b1.risk_evidence] == [e.layer_id for e in b2.risk_evidence]
        assert [e.layer_id for e in b1.economics_evidence] == [e.layer_id for e in b2.economics_evidence]

    def test_hard_blockers_identical_across_sessions(self):
        b1, _ = self._make_and_run()
        b2, _ = self._make_and_run()
        assert sorted(b1.hard_blockers()) == sorted(b2.hard_blockers())

    def test_envelope_insertion_order_preserved(self):
        _, envs = self._make_and_run()
        assert [e.layer_id for e in envs] == ["L1", "L2", "L3", "L4", "L6", "L11"]


# ─────────────────────────────────────────────────────────────────────────
# Invariant 3 — legacy blockers surface in shadow bundle
# ─────────────────────────────────────────────────────────────────────────


class TestBlockerSurfacing:
    def test_single_fail_layer_surfaces_blocker(self):
        sess = _fresh_session()
        sess.capture(_legacy("L6", status="FAIL", blockers=["RISK_CEILING_EXCEEDED"]))
        bundle, _ = sess.try_build()
        assert bundle is not None
        assert "RISK_CEILING_EXCEEDED" in bundle.hard_blockers()

    def test_multiple_fail_layers_surface_all_blockers(self):
        sess = _fresh_session()
        sess.capture(_legacy("L3", status="FAIL", blockers=["STRUCTURE_INVALID"]))
        sess.capture(_legacy("L6", status="FAIL", blockers=["RISK_CEILING"]))
        sess.capture(_legacy("L8", status="FAIL", blockers=["INTEGRITY_LOW"]))
        bundle, _ = sess.try_build()
        assert bundle is not None
        blockers = set(bundle.hard_blockers())
        assert {"STRUCTURE_INVALID", "RISK_CEILING", "INTEGRITY_LOW"} <= blockers

    def test_meta_plane_blockers_excluded(self):
        """L13/L15 are advisory — blockers on them MUST NOT gate L12."""
        sess = _fresh_session()
        sess.capture(_legacy("L13", status="FAIL", blockers=["GOVERNANCE_CONCERN"]))
        sess.capture(_legacy("L15", status="FAIL", blockers=["SOVEREIGNTY_WARN"]))
        bundle, _ = sess.try_build()
        assert bundle is not None
        assert bundle.hard_blockers() == []


# ─────────────────────────────────────────────────────────────────────────
# Invariant 4 — layer failure isolation
# ─────────────────────────────────────────────────────────────────────────


class TestLayerIsolation:
    def test_leaky_layer_does_not_drop_others(self):
        sess = _fresh_session()
        leaky = _legacy("L6", extra_features={"equity": 10_000.0})
        sess.capture(_legacy("L1"))
        sess.capture(leaky)
        sess.capture(_legacy("L11"))
        captured = {e.layer_id for e in sess.envelopes()}
        assert captured == {"L1", "L11"}
        assert len(sess.failures()) == 1
        assert sess.failures()[0].layer_id == "L6"

    def test_bundle_still_builds_after_partial_failure(self):
        sess = _fresh_session()
        sess.capture(_legacy("L1"))
        sess.capture(_legacy("L6", extra_features={"balance": 5_000.0}))  # leaks
        sess.capture(_legacy("L11"))
        bundle, diag = sess.try_build()
        assert diag is None
        assert bundle is not None
        assert {e.layer_id for e in bundle.context_evidence} == {"L1"}
        assert {e.layer_id for e in bundle.economics_evidence} == {"L11"}
        assert bundle.risk_evidence == []  # L6 never made it


# ─────────────────────────────────────────────────────────────────────────
# Invariant 5 — no account-state / no verdict authority on bundle
# ─────────────────────────────────────────────────────────────────────────


class TestNoAuthorityLeak:
    _FORBIDDEN_KEYS = {"balance", "equity", "margin", "free_margin", "account_balance"}

    def _walk(self, obj: Any) -> list[str]:
        hits: list[str] = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k.lower() in self._FORBIDDEN_KEYS:
                    hits.append(k)
                hits.extend(self._walk(v))
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                hits.extend(self._walk(item))
        return hits

    def test_no_account_state_anywhere_in_serialized_bundle(self):
        sess = _fresh_session()
        sess.ingest_chain_result(SimpleNamespace(l1=_legacy("L1"), l2=_legacy("L2"), l3=_legacy("L3")))
        sess.capture(_legacy("L11"))
        bundle, _ = sess.try_build()
        assert bundle is not None
        dumped = bundle.model_dump(mode="json")
        assert self._walk(dumped) == []

    def test_bundle_has_no_verdict_or_direction_field(self):
        sess = _fresh_session()
        sess.capture(_legacy("L2"))
        bundle, _ = sess.try_build()
        assert bundle is not None
        assert not hasattr(bundle, "verdict")
        assert not hasattr(bundle, "direction")
        assert not hasattr(bundle, "execute")

    def test_v11_never_appears_in_any_plane(self):
        sess = _fresh_session()
        sess.capture(_legacy("V11"))
        sess.capture(_legacy("L2"))
        bundle, _ = sess.try_build()
        assert bundle is not None
        all_layers = {e.layer_id for e in bundle.all_envelopes()}
        assert "V11" not in all_layers


# ─────────────────────────────────────────────────────────────────────────
# Invariant 6 — opt-in: constructing a session alone has no side effects
# ─────────────────────────────────────────────────────────────────────────


class TestOptInContract:
    def test_session_construction_is_pure(self):
        # No imports or side effects; purely constructing the session
        # must not touch global state. This test simply documents intent
        # — the failure mode would be an import-time side effect.
        s1 = _fresh_session()
        s2 = _fresh_session()
        assert s1 is not s2
        assert s1.envelopes() == s2.envelopes() == []
        assert s1.failures() == s2.failures() == []

    def test_session_without_capture_still_builds_empty_bundle(self):
        sess = _fresh_session()
        bundle, diag = sess.try_build()
        assert diag is None
        assert bundle is not None
        assert bundle.all_envelopes() == []
        assert bundle.hard_blockers() == []
