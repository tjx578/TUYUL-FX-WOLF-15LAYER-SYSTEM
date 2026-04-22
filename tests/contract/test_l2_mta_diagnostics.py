from __future__ import annotations

from analysis.layers.L2_constitutional import L2ConstitutionalGovernor


def _l1_pass() -> dict:
    return {"valid": True, "continuation_allowed": True, "status": "PASS"}


def _base_analysis() -> dict:
    return {
        "valid": True,
        "alignment_strength": 0.42,
        "hierarchy_followed": False,
        "aligned": False,
        "available_timeframes": 4,
        "per_tf_bias": {
            "D1": {"p_bull": 0.78},
            "H4": {"p_bull": 0.22},
            "H1": {"p_bull": 0.25},
            "M15": {"p_bull": 0.50},
        },
        "candle_age_by_tf": {"D1": 58000, "H4": 9000, "H1": 1800, "M15": 300},
    }


def test_l2_warn_exposes_primary_conflict_without_hard_stop() -> None:
    gov = L2ConstitutionalGovernor()
    result = gov.evaluate(
        l1_output=_l1_pass(),
        l2_analysis=_base_analysis(),
        symbol="GBPAUD",
        candle_counts={"D1": 15, "H4": 60, "H1": 44, "M15": 120},
    )

    assert result["status"] == "WARN"
    assert result["continuation_allowed"] is True
    assert result["blocker_codes"] == []
    assert "MTA_HIERARCHY_VIOLATED" in result["warning_codes"]
    assert "LOW_ALIGNMENT_BAND" in result["warning_codes"]
    assert result["mta_diagnostics"]["primary_conflict"] == "D1_H4_DIRECTION_CONFLICT"
    assert result["mta_diagnostics"]["alignment_score"] == 0.42
    assert result["mta_diagnostics"]["required_alignment"] == 0.65


def test_l2_pass_still_exposes_diagnostics() -> None:
    gov = L2ConstitutionalGovernor()
    analysis = {
        "valid": True,
        "alignment_strength": 0.91,
        "hierarchy_followed": True,
        "aligned": True,
        "available_timeframes": 6,
        "per_tf_bias": {
            "MN": {"p_bull": 0.69},
            "W1": {"p_bull": 0.70},
            "D1": {"p_bull": 0.73},
            "H4": {"p_bull": 0.71},
            "H1": {"p_bull": 0.68},
            "M15": {"p_bull": 0.62},
        },
        "candle_age_by_tf": {"MN": 120000, "W1": 80000, "D1": 58000, "H4": 9000, "H1": 1800, "M15": 300},
    }

    result = gov.evaluate(
        l1_output=_l1_pass(),
        l2_analysis=analysis,
        symbol="EURUSD",
        candle_counts={"MN": 3, "W1": 8, "D1": 15, "H4": 60, "H1": 44, "M15": 120},
    )

    assert result["status"] == "PASS"
    assert result["mta_diagnostics"]["direction_consensus"] == "bullish"
    assert result["mta_diagnostics"]["primary_conflict"] is None
    assert result["mta_diagnostics"]["per_tf_bias"]["D1"] == "BULLISH"
