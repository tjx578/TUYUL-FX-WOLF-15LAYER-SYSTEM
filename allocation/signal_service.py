from __future__ import annotations

import time
from typing import Any

from allocation.signal_registry import SignalRegistry
from config_loader import load_pairs
from schemas.signal_contract import FROZEN_SIGNAL_CONTRACT_VERSION, SignalContract
from schemas.validator import validate_signal_contract
from storage.l12_cache import get_verdict


class SignalService:
    """Read/write helper around signal registry with frozen contract enforcement."""

    def __init__(self) -> None:
        self._registry = SignalRegistry()

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        contract = SignalContract(
            signal_id=str(payload.get("signal_id", f"SIG-{int(time.time())}")),
            symbol=str(payload.get("symbol", payload.get("pair", "UNKNOWN"))).upper(),
            verdict=str(payload.get("verdict", "HOLD")),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            direction=payload.get("direction"),
            entry_price=_to_opt_float(payload.get("entry_price")),
            stop_loss=_to_opt_float(payload.get("stop_loss")),
            take_profit_1=_to_opt_float(payload.get("take_profit_1")),
            risk_reward_ratio=_to_opt_float(payload.get("risk_reward_ratio")),
            scores={
                "wolf_score": float((payload.get("scores") or {}).get("wolf_score", 0.0) or 0.0),
                "tii_score": float((payload.get("scores") or {}).get("tii_score", 0.0) or 0.0),
                "frpc_score": float((payload.get("scores") or {}).get("frpc_score", 0.0) or 0.0),
            },
            timestamp=float(payload.get("timestamp", time.time())),
            expires_at=_to_opt_float(payload.get("expires_at")),
        ).as_dict()

        ok, errors = validate_signal_contract(contract)
        if not ok:
            raise ValueError("; ".join(errors))

        self._registry.publish(contract)
        return contract

    def get(self, signal_id: str) -> dict[str, Any] | None:
        for item in self.list_all():
            if item.get("signal_id") == signal_id:
                return item
        return None

    def list_by_symbol(self, symbol: str) -> list[dict[str, Any]]:
        symbol = symbol.upper()
        return [item for item in self.list_all() if str(item.get("symbol", "")).upper() == symbol]

    def list_all(self) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}

        for item in self._registry.all_signals():
            sid = str(item.get("signal_id", f"NO_ID:{item.get('symbol', 'UNK')}"))
            merged[sid] = item

        for pair in load_pairs():
            symbol = str(pair.get("symbol", "")).upper().strip()
            if not symbol:
                continue
            verdict = get_verdict(symbol)
            if not verdict:
                continue

            payload = {
                "contract_version": FROZEN_SIGNAL_CONTRACT_VERSION,
                "signal_id": str(verdict.get("signal_id", f"SIG-CACHE-{symbol}")),
                "symbol": symbol,
                "verdict": str(verdict.get("verdict", "HOLD")),
                "confidence": float(verdict.get("confidence", 0.0) or 0.0),
                "direction": verdict.get("direction"),
                "entry_price": _to_opt_float(verdict.get("entry_price")),
                "stop_loss": _to_opt_float(verdict.get("stop_loss")),
                "take_profit_1": _to_opt_float(verdict.get("take_profit_1")),
                "risk_reward_ratio": _to_opt_float(verdict.get("risk_reward_ratio")),
                "scores": {
                    "wolf_score": float((verdict.get("scores") or {}).get("wolf_score", 0.0) or 0.0),
                    "tii_score": float((verdict.get("scores") or {}).get("tii_score", 0.0) or 0.0),
                    "frpc_score": float((verdict.get("scores") or {}).get("frpc_score", 0.0) or 0.0),
                },
                "timestamp": float(verdict.get("timestamp", time.time()) or time.time()),
                "expires_at": _to_opt_float(verdict.get("expires_at")),
            }
            ok, _errors = validate_signal_contract(payload)
            if ok:
                merged[payload["signal_id"]] = payload

        return sorted(merged.values(), key=lambda x: float(x.get("timestamp", 0.0)), reverse=True)


def _to_opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
