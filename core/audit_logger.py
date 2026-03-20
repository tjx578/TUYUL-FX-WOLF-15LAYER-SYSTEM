import logging
from datetime import datetime


def log_layer12_decision(trade_id: str, verdict_result: dict):
    log_entry = {
        "trade_id": trade_id,
        "timestamp": datetime.utcnow().isoformat(),
        "regime": verdict_result["regime"],
        "thresholds": verdict_result["thresholds"],
        "tii": verdict_result["tii"],
        "frpc": verdict_result["frpc"],
        "meta_results": verdict_result["meta_results"],
        "verdict": verdict_result["verdict"],
        "risk_multiplier": verdict_result["risk_multiplier"],
    }
    logging.info(f"[LAYER12 DECISION] {log_entry}")
