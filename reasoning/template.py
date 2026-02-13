"""
Template populator for Wolf 15-Layer Reasoning Engine

Formats reasoning engine output for display and export.
"""

import json


class Wolf15LayerTemplatePopulator:
    """
    Mengisi Wolf 15-Layer Output Template dengan data dari Reasoning Engine.
    Format template TIDAK DIUBAH - hanya nilai yang diisi.
    """

    def __init__(self, engine_output: dict):
        self.data = engine_output

    def get_l4_scores(self) -> str:
        """Generate L4 score display"""
        scores = self.data["scores"]
        return f"""
F-Score: [{scores["f_score"]}/7] → F-Bias: [{"STRONG" if scores["f_score"] >= 5 else "WEAK"}]
T-Score: [{scores["t_score"]}/13] → T-Bias: [{"STRONG" if scores["t_score"] >= 9 else "WEAK"}]
Wolf 30: [{scores["wolf_30"]}/30] → Status: [{self.data["wolf_status"]}]
"""

    def get_l12_verdict(self) -> str:
        """Generate L12 verdict display"""
        return f"""
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║   ∴ FINAL VERDICT: {self.data["verdict"]:^40}   ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝

CONFIDENCE : {self.data["confidence"]}
WOLF STATUS: {self.data["wolf_status"]}
GATES      : {self.data["gates"]["passed"]}/{self.data["gates"]["total"]}
"""

    def get_execution_table(self) -> str:
        """Generate execution parameters table (TP1 ONLY)"""
        exec_data = self.data["execution"]
        return f"""
┌─────────────────┬────────────────────┬────────────────────────────────┐
│ Entry           │ {exec_data["entry"]:<18} │ Constitutional entry          │
│ Stop Loss       │ {exec_data["stop_loss"]:<18} │ Structure invalidation        │
│ Take Profit 1   │ {exec_data["take_profit_1"]:<18} │ TP1_ONLY execution mode       │
│ RR Ratio        │ 1:{exec_data["rr_ratio"]:<16} │ {"≥ 1:2 PASS ✅" if exec_data["rr_ratio"] >= 2 else "< 1:2 FAIL ❌"}         │
│ Execution Mode  │ TP1_ONLY           │ Single target strategy        │
└─────────────────┴────────────────────┴────────────────────────────────┘
"""

    def to_json(self) -> str:
        """Export as JSON for L14"""
        return json.dumps(self.data, indent=2, default=str)
