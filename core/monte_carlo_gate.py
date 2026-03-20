def monte_carlo_gate(win_rate: float, profit_factor: float, thresholds: dict) -> bool:
    return win_rate >= thresholds["mc_win"] and profit_factor >= thresholds["mc_pf"]
