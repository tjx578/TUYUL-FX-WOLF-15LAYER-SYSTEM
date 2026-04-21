"""Tests for contracts.adapters — P0.5 envelope projection."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from contracts.adapters import (
    default_plane_for_layer,
    layer_dict_to_envelope,
)
from contracts.layer_envelope import LayerEnvelope

SIGNAL_ID = "sig_p05_adapter_test"
SYMBOL = "EURUSD"


def _legacy_l2_payload(status: str = "PASS", blockers: list[str] | None = None) -> dict:
    return {
        "layer": "L2",
        "layer_version": "1.0.0",
        "timestamp": "2026-04-21T12:00:00+00:00",
        "input_ref": "EURUSD_L2_run",
        "status": status,
        "continuation_allowed": status in ("PASS", "WARN"),
        "blocker_codes": blockers or [],
        "warning_codes": [],
        "fallback_class": "NO_FALLBACK",
        "freshness_state": "FRESH",
        "warmup_state": "READY",
        "coherence_band": "HIGH",
        "coherence_score": 0.8234,
        "features": {
            "alignment_score": 0.8234,
            "hierarchy_followed": True,
            "aligned": True,
        },
        "routing": {"source_used": ["H1", "H4"], "fallback_used": False, "next_legal_targets": ["L3"]},
        "audit": {"rule_hits": ["freshness_state=FRESH"], "blocker_triggered": False, "notes": []},
    }


class TestDefaultPlaneForLayer:
    def test_foundation_layers_map_to_context_and_alpha(self):
        assert default_plane_for_layer("L1") == "context"
        assert default_plane_for_layer("L2") == "alpha"
        assert default_plane_for_layer("L3") == "alpha"

    def test_risk_chain_planes(self):
        assert default_plane_for_layer("L6") == "risk"
        assert default_plane_for_layer("L10") == "portfolio"
        assert default_plane_for_layer("L11") == "economics"

    def test_governance_layers_are_meta(self):
        assert default_plane_for_layer("L13") == "meta"
        assert default_plane_for_layer("L15") == "meta"

    def test_v11_is_post_authority_veto(self):
        assert default_plane_for_layer("V11") == "post_authority_veto"

    def test_unknown_layer_raises(self):
        with pytest.raises(KeyError):
            default_plane_for_layer("L99")


class TestLayerDictToEnvelope:
    def test_passthrough_projects_canonical_fields(self):
        env = layer_dict_to_envelope(_legacy_l2_payload(), signal_id=SIGNAL_ID, symbol=SYMBOL)
        assert isinstance(env, LayerEnvelope)
        assert env.layer_id == "L2"
        assert env.plane == "alpha"
        assert env.status == "PASS"
        assert env.score == pytest.approx(0.8234)
        assert env.direction == "NONE"  # adapters never fabricate direction
        assert env.module == "analysis.layers.L2_constitutional"

    def test_warn_status_maps_to_degraded(self):
        env = layer_dict_to_envelope(_legacy_l2_payload(status="WARN"), signal_id=SIGNAL_ID, symbol=SYMBOL)
        assert env.status == "DEGRADED"
        assert env.is_degraded() is True
        assert env.is_blocking() is False  # no blockers → not hard-reject

    def test_fail_with_blockers_is_blocking(self):
        env = layer_dict_to_envelope(
            _legacy_l2_payload(status="FAIL", blockers=["MTA_HIERARCHY_VIOLATED"]),
            signal_id=SIGNAL_ID,
            symbol=SYMBOL,
        )
        assert env.status == "FAIL"
        assert env.blockers == ["MTA_HIERARCHY_VIOLATED"]
        assert env.is_blocking() is True

    def test_features_routing_audit_land_in_evidence(self):
        env = layer_dict_to_envelope(_legacy_l2_payload(), signal_id=SIGNAL_ID, symbol=SYMBOL)
        assert "features" in env.evidence
        assert "routing" in env.evidence
        assert "audit" in env.evidence
        assert env.evidence["features"]["aligned"] is True
        # context bag captures routing-relevant scalars
        assert env.evidence["context"]["coherence_band"] == "HIGH"
        assert env.evidence["context"]["freshness_state"] == "FRESH"

    def test_account_state_leak_in_features_is_rejected(self):
        payload = _legacy_l2_payload()
        payload["features"]["balance"] = 10_000.0  # deliberate leak
        with pytest.raises(ValueError, match="account state"):
            layer_dict_to_envelope(payload, signal_id=SIGNAL_ID, symbol=SYMBOL)

    def test_timestamp_is_parsed(self):
        env = layer_dict_to_envelope(_legacy_l2_payload(), signal_id=SIGNAL_ID, symbol=SYMBOL)
        assert env.finished_at == datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        assert env.started_at == env.finished_at  # absent → mirror finished_at

    def test_explicit_plane_override_wins(self):
        env = layer_dict_to_envelope(
            _legacy_l2_payload(),
            signal_id=SIGNAL_ID,
            symbol=SYMBOL,
            plane="meta",
        )
        assert env.plane == "meta"

    def test_missing_layer_raises(self):
        payload = _legacy_l2_payload()
        payload.pop("layer")
        with pytest.raises(ValueError, match="layer_id"):
            layer_dict_to_envelope(payload, signal_id=SIGNAL_ID, symbol=SYMBOL)

    def test_accepts_object_with_to_dict(self):
        class Fake:
            def to_dict(self):
                return _legacy_l2_payload()

        env = layer_dict_to_envelope(Fake(), signal_id=SIGNAL_ID, symbol=SYMBOL, layer_id="L2")
        assert env.layer_id == "L2"
        assert env.status == "PASS"

    def test_rejects_unsupported_input_type(self):
        with pytest.raises(TypeError):
            layer_dict_to_envelope("not a mapping", signal_id=SIGNAL_ID, symbol=SYMBOL)  # type: ignore[arg-type]

    def test_direction_never_fabricated_from_missing_field(self):
        # Even if result carries no direction, envelope defaults to NONE.
        payload = _legacy_l2_payload()
        payload.pop("blocker_codes", None)
        env = layer_dict_to_envelope(payload, signal_id=SIGNAL_ID, symbol=SYMBOL)
        assert env.direction == "NONE"

    def test_v11_layer_routes_to_post_authority_veto(self):
        payload = _legacy_l2_payload()
        payload["layer"] = "V11"
        env = layer_dict_to_envelope(payload, signal_id=SIGNAL_ID, symbol=SYMBOL)
        assert env.plane == "post_authority_veto"

    def test_stale_after_ms_override(self):
        env = layer_dict_to_envelope(
            _legacy_l2_payload(),
            signal_id=SIGNAL_ID,
            symbol=SYMBOL,
            stale_after_ms=5_000,
        )
        assert env.stale_after_ms == 5_000
