"""Shared existing closed-candle fingerprint semantics; no source attestation."""

import hashlib
import json


def _sha256(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def candle_material_hash(candle):
    return _sha256(
        {
            "symbol": candle.symbol,
            "timeframe": candle.timeframe,
            "open_time_utc": candle.open_time_utc,
            "close_time_utc": candle.close_time_utc,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
        }
    )


def candle_evidence_hash(candle):
    payload = candle.model_dump(mode="json")
    payload.pop("candle_evidence_id", None)
    return _sha256(payload)
