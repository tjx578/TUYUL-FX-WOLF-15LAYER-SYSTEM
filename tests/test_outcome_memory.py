from __future__ import annotations

from analysis.outcome_memory import label_outcome, summarize_outcome_memory


def test_label_outcome_from_future_extremes_for_buy_target():
    record = label_outcome(
        {
            "timestamp": "2026-06-25T08:00:00Z",
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.1000,
            "future_high": 1.1012,
            "future_low": 1.0998,
        },
        target_pips=8,
        stop_pips=5,
    )

    assert record.outcome == "TARGET_REACHED"
    assert record.mfe_pips == 12.0
    assert record.mae_pips == 2.0


def test_label_outcome_from_future_extremes_for_sell_stop_risk():
    record = label_outcome(
        {
            "timestamp": "2026-06-25T08:00:00Z",
            "symbol": "USDJPY",
            "direction": "SELL",
            "entry_price": 160.00,
            "future_high": 160.08,
            "future_low": 159.98,
        },
        target_pips=8,
        stop_pips=5,
    )

    assert record.outcome == "STOP_RISK"
    assert record.mfe_pips == 2.0
    assert record.mae_pips == 8.0


def test_summarize_outcome_memory_penalizes_repeated_failure_cluster():
    events = [
        {"symbol": "USDCAD", "direction": "BUY", "forward_mfe_pips": 1, "forward_mae_pips": 7},
        {"symbol": "USDCAD", "direction": "BUY", "forward_mfe_pips": 2, "forward_mae_pips": 8},
        {"symbol": "USDCAD", "direction": "BUY", "forward_mfe_pips": 0, "forward_mae_pips": 6},
    ]

    summary = summarize_outcome_memory(events, min_samples_for_memory=3, stop_pips=5)

    assert summary["data_ready"] is True
    assert summary["failure_rate"] == 1.0
    assert summary["by_symbol_direction"]["USDCAD:BUY"]["memory_action"] == "PENALIZE_PROMOTION"
