from __future__ import annotations

from constitution.adaptive_threshold_governor import AdaptiveThresholdGovernor, parse_history_ratio


class _StubController:
    def __init__(self, *, adjustment_factor: float = 1.05, reason: str = "ok", freeze_thresholds: bool = False):
        self.adjustment_factor = adjustment_factor
        self.reason = reason
        self.freeze_thresholds = freeze_thresholds

    def recompute(self, frpc_data: dict | None = None) -> dict:
        return {
            "reason": self.reason,
            "freeze_thresholds": self.freeze_thresholds,
            "proposed": {"adjustment_factor": self.adjustment_factor},
            "frpc_seen": frpc_data or {},
        }


def _frpc_payload() -> dict[str, float]:
    return {
        "gradient": 0.001,
        "mean_energy": 0.2,
        "integrity_index": 0.98,
    }


def test_parse_history_ratio_extracts_fraction() -> None:
    assert parse_history_ratio("insufficient_data_5/30") == 5 / 30
    assert parse_history_ratio("insufficient_data_30/30") == 1.0
    assert parse_history_ratio("missing") == 0.0


def test_shadow_mode_keeps_base_threshold_but_audits_adjustment() -> None:
    governor = AdaptiveThresholdGovernor(
        controller=_StubController(adjustment_factor=1.08),
        mode="shadow",
    )

    result = governor.get_adjusted(
        layer="L7",
        metric="win_probability",
        base_threshold=0.55,
        frpc_data=_frpc_payload(),
        source_completeness=1.0,
    )

    assert result.mode == "shadow"
    assert result.base == 0.55
    assert result.adjusted == 0.55
    assert result.adjustment_factor == 1.08
    assert result.decision_reason == "ok"
    assert result.audit_id
    assert result.audit_signature


def test_live_mode_applies_adjustment_within_budget() -> None:
    governor = AdaptiveThresholdGovernor(
        controller=_StubController(adjustment_factor=1.04),
        mode="live",
    )

    result = governor.get_adjusted(
        layer="L8",
        metric="integrity",
        base_threshold=0.75,
        frpc_data=_frpc_payload(),
        source_completeness=1.0,
    )

    assert result.mode == "live"
    assert result.adjusted == 0.78
    assert result.decision_reason == "ok"


def test_incomplete_sources_keep_base_even_in_live_mode() -> None:
    governor = AdaptiveThresholdGovernor(
        controller=_StubController(adjustment_factor=1.04),
        mode="live",
    )

    result = governor.get_adjusted(
        layer="L8",
        metric="integrity",
        base_threshold=0.75,
        frpc_data=_frpc_payload(),
        source_completeness=0.5,
    )

    assert result.adjusted == 0.75
    assert result.decision_reason == "source_incomplete"


def test_freeze_keeps_base_threshold() -> None:
    governor = AdaptiveThresholdGovernor(
        controller=_StubController(adjustment_factor=1.04, reason="meta_drift=0.02", freeze_thresholds=True),
        mode="live",
    )

    result = governor.get_adjusted(
        layer="L9",
        metric="structure_score",
        base_threshold=0.65,
        frpc_data=_frpc_payload(),
        source_completeness=1.0,
    )

    assert result.adjusted == 0.65
    assert result.freeze_thresholds is True
    assert result.decision_reason == "controller_freeze:meta_drift=0.02"


def test_budget_exceeded_keeps_base_threshold() -> None:
    governor = AdaptiveThresholdGovernor(
        controller=_StubController(adjustment_factor=1.12),
        mode="live",
    )

    result = governor.get_adjusted(
        layer="L7",
        metric="win_probability",
        base_threshold=0.55,
        frpc_data=_frpc_payload(),
        source_completeness=1.0,
    )

    assert result.adjusted == 0.55
    assert result.decision_reason == "daily_budget_exceeded"
