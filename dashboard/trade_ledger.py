from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime

from schemas.trade_models import RiskMode, Trade, TradeLeg, TradeStatus

from storage.redis_client import redis_client


class TradeLedger:
    """Read-oriented trade ledger for API and WS consumers."""

    _memory_trades: dict[str, Trade] = {}

    def get_trade(self, trade_id: str) -> Trade | None:
        if trade_id in self._memory_trades:
            return self._memory_trades[trade_id]

        with contextlib.suppress(Exception):
            raw = redis_client.client.get(f"TRADE:{trade_id}")
            if isinstance(raw, str):
                trade = self._from_dict(json.loads(raw))
                self._memory_trades[trade_id] = trade
                return trade
        return None

    def get_active_trades(self) -> list[Trade]:
        trades: dict[str, Trade] = dict(self._memory_trades)
        with contextlib.suppress(Exception):
            for key in redis_client.client.scan_iter("TRADE:*"):
                trade_id = str(key).split(":", 1)[1]
                raw = redis_client.client.get(key)
                if isinstance(raw, str):
                    trades[trade_id] = self._from_dict(json.loads(raw))

        return [
            t for t in sorted(trades.values(), key=lambda x: x.updated_at, reverse=True)
            if t.status not in {TradeStatus.CANCELLED, TradeStatus.CLOSED, TradeStatus.SKIPPED}
        ]

    def _from_dict(self, data: dict) -> Trade:
        legs_payload = data.get("legs") or []
        if not legs_payload:
            legs_payload = [{
                "leg": 1,
                "entry": float(data.get("entry_price", 0.0) or 0.0),
                "sl": float(data.get("stop_loss", 0.0) or 0.0),
                "tp": float(data.get("take_profit", 0.0) or 0.0),
                "lot": float(data.get("lot_size", 0.01) or 0.01),
                "status": data.get("status", "INTENDED"),
            }]

        legs = [TradeLeg(**leg) for leg in legs_payload]

        status_raw = str(data.get("status", "INTENDED"))
        try:
            status = TradeStatus(status_raw)
        except ValueError:
            status = TradeStatus.INTENDED

        risk_mode_raw = str(data.get("risk_mode", "FIXED"))
        try:
            risk_mode = RiskMode(risk_mode_raw)
        except ValueError:
            risk_mode = RiskMode.FIXED

        return Trade(
            trade_id=str(data.get("trade_id", "")),
            signal_id=str(data.get("signal_id", "")),
            account_id=str(data.get("account_id", "")),
            pair=str(data.get("pair", "")),
            direction=str(data.get("direction", "BUY")),
            status=status,
            risk_mode=risk_mode,
            total_risk_percent=float(data.get("total_risk_percent", 0.1) or 0.1),
            total_risk_amount=float(data.get("total_risk_amount", 0.01) or 0.01),
            legs=legs,
            created_at=_parse_dt(data.get("created_at")),
            updated_at=_parse_dt(data.get("updated_at")),
            close_reason=data.get("close_reason"),
            pnl=float(data["pnl"]) if data.get("pnl") is not None else None,
        )


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(UTC)
