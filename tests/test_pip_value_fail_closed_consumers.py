"""Every pip-value consumer fails closed for an unconfigured pair and uses explicit values for the 30 pairs."""

from pathlib import Path

import pytest

from analysis.layers.L10_position_sizing import L10PositionAnalyzer
from config.pip_values import WOLF15_XM_30_V1_PAIRS, PipLookupError, get_pip_value
from risk.risk_manager import RiskManager

ROOT = Path(__file__).resolve().parents[1]
BUY = {"entry": 1.1000, "stop_loss": 1.0950, "take_profit": 1.1100, "direction": "BUY"}


def test_no_module_references_a_default_pip_value():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if any(part in {"tests", ".venv", "node_modules", "ingest"} for part in path.parts):
            continue  # ingest/spread_estimator's DEFAULT_PIP_VALUE is a pip *size*, not a monetary value
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "DEFAULT_PIP_VALUE" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_l10_unknown_pair_is_invalid_with_zero_lot():
    result = L10PositionAnalyzer().analyze(trade_params=BUY, pair="USDSEK", risk_data={})
    assert result["valid"] is False
    assert result["position_ok"] is False
    assert "pip_value_not_configured" in result["degraded_fields"]
    assert "PIP_VALUE_NOT_CONFIGURED" in result["warnings"]


@pytest.mark.parametrize("pair", ["CADJPY", "CHFJPY", "AUDCHF", "NZDCAD", "EURNZD", "CADCHF", "NZDCHF"])
def test_l10_uses_single_source_explicit_values_for_previously_defaulted_pairs(pair):
    result = L10PositionAnalyzer().analyze(trade_params=BUY, pair=pair, risk_data={})
    assert result["pip_value"] == get_pip_value(pair)
    assert "pip_value_not_configured" not in result["degraded_fields"]


@pytest.mark.parametrize("pair", WOLF15_XM_30_V1_PAIRS)
def test_l10_never_degrades_pip_value_for_universe_pairs(pair):
    result = L10PositionAnalyzer().analyze(trade_params=BUY, pair=pair, risk_data={})
    assert "pip_value_not_configured" not in result["degraded_fields"]


def test_risk_manager_unknown_pair_fails_closed():
    with pytest.raises(PipLookupError):
        RiskManager().calculate_position(entry_price=1.1, stop_loss_price=1.095, pair="USDSEK", risk_percent=0.01)


def test_risk_manager_jpy_scaling_and_non_usd_quote():
    manager = RiskManager()
    jpy = manager.calculate_position(
        entry_price=150.00, stop_loss_price=149.50, pair="CADJPY", risk_percent=0.01, balance=10_000
    )
    chf = manager.calculate_position(
        entry_price=0.6000, stop_loss_price=0.5950, pair="CADCHF", risk_percent=0.01, balance=10_000
    )
    assert round(jpy["pips_at_risk"], 6) == 50.0 and jpy["pip_value"] == 6.67
    assert round(chf["pips_at_risk"], 6) == 50.0 and chf["pip_value"] == 10.00
