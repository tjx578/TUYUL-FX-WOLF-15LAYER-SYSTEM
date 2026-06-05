"""Read-oriented trade ledger for API and WS consumers.

Canonical location — moved from dashboard/trade_ledger.py (PR-003).
"""

from __future__ import annotations

import contextlib
import datetime
import json

from infrastructure.redis_client import get_client
from schemas.trade_models import CloseReason, RiskMode, Trade, TradeLeg, TradeStatus, is_valid_transition
from storage.postgres_client import pg_client
from storage.redis_client import redis_client


class TradeLedger:
    """Read-oriented trade ledger for API and WS consumers."""

    _memory_trades: dict[str, Trade] = {}

    def create_trade(
        self,
        *,
        signal_id: str,
        account_id: str,
        pair: str,
        direction: str,
        risk_mode: str | RiskMode,
        total_risk_percent: float,
        total_risk_amount: float,
        legs: list[dict[str, object]],
    ) -> Trade:
        now = datetime.datetime.now(datetime.UTC)
        trade_id = self._new_trade_id(now)
        parsed_risk_mode = risk_mode if isinstance(risk_mode, RiskMode) else RiskMode(str(risk_mode))
        parsed_legs = [
            TradeLeg(
                leg=int(float(str(leg.get("leg", index)))),
                entry=float(str(leg.get("entry", 0.0))),
                sl=float(str(leg.get("sl", 0.0))),
                tp=float(str(leg.get("tp", 0.0))),
                lot=float(str(leg.get("lot", 0.0))),
                status=TradeStatus(str(leg.get("status", TradeStatus.INTENDED.value))),
            )
            for index, leg in enumerate(legs, start=1)
        ]
        trade = Trade(
            trade_id=trade_id,
            signal_id=signal_id,
            account_id=account_id,
            pair=pair,
            direction=direction,
            status=TradeStatus.INTENDED,
            risk_mode=parsed_risk_mode,
            total_risk_percent=total_risk_percent,
            total_risk_amount=total_risk_amount,
            legs=parsed_legs,
            created_at=now,
            updated_at=now,
        )
        self._memory_trades[trade.trade_id] = trade
        self._persist_trade(trade)
        return trade

    def update_status(
        self,
        trade_id: str,
        new_status: TradeStatus,
        *,
        close_reason: CloseReason | None = None,
        pnl: float | None = None,
    ) -> bool:
        trade = self.get_trade(trade_id)
        if trade is None or not is_valid_transition(trade.status, new_status):
            return False

        updated_legs = [leg.model_copy(update={"status": new_status}) for leg in trade.legs]
        updates: dict[str, object] = {
            "status": new_status,
            "legs": updated_legs,
            "updated_at": datetime.datetime.now(datetime.UTC),
        }
        if new_status == TradeStatus.CLOSED:
            updates["close_reason"] = close_reason
            updates["pnl"] = pnl

        updated = trade.model_copy(update=updates)
        self._memory_trades[trade_id] = updated
        self._persist_trade(updated)
        return True

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

    async def get_trade_async(self, trade_id: str) -> Trade | None:
        if trade_id in self._memory_trades:
            return self._memory_trades[trade_id]

        with contextlib.suppress(Exception):
            client = await get_client()
            raw = await client.get(f"TRADE:{trade_id}")
            if isinstance(raw, str):
                trade = self._from_dict(json.loads(raw))
                self._memory_trades[trade_id] = trade
                return trade

        with contextlib.suppress(Exception):
            row = await pg_client.fetchrow(
                """
                SELECT trade_id, signal_id, account_id, pair, direction, status, risk_mode,
                       total_risk_percent, total_risk_amount, pnl, close_reason, legs,
                       created_at, updated_at, closed_at
                FROM trade_history
                WHERE trade_id = $1
                """,
                trade_id,
            )
            if row is not None:
                data = dict(row)
                for field in ("created_at", "updated_at", "closed_at"):
                    if data.get(field) is not None:
                        data[field] = data[field].isoformat()
                trade = self._from_dict(data)
                self._memory_trades[trade_id] = trade
                return trade
        return None

    def get_active_trades(self) -> list[Trade]:
        trades: dict[str, Trade] = dict(self._memory_trades)
        with contextlib.suppress(Exception):
            for key in redis_client.client.scan_iter(match="TRADE:*"):
                key_str: str = key if isinstance(key, str) else str(key)
                trade_id = key_str.split(":", 1)[1]
                raw = redis_client.client.get(key_str)
                if isinstance(raw, str):
                    trades[trade_id] = self._from_dict(json.loads(raw))

        return [
            t
            for t in sorted(trades.values(), key=lambda x: x.updated_at, reverse=True)
            if t.status not in {TradeStatus.CANCELLED, TradeStatus.CLOSED, TradeStatus.SKIPPED}
        ]

    def get_trades_by_account(self, account_id: str) -> list[Trade]:
        trades: dict[str, Trade] = dict(self._memory_trades)
        with contextlib.suppress(Exception):
            for key in redis_client.client.scan_iter(match="TRADE:*"):
                key_str: str = key if isinstance(key, str) else str(key)
                trade_id = key_str.split(":", 1)[1]
                raw = redis_client.client.get(key_str)
                if isinstance(raw, str):
                    trades[trade_id] = self._from_dict(json.loads(raw))

        return [
            trade
            for trade in sorted(trades.values(), key=lambda x: x.updated_at, reverse=True)
            if trade.account_id == account_id
        ]

    async def get_active_trades_async(self) -> list[Trade]:
        trades: dict[str, Trade] = dict(self._memory_trades)
        with contextlib.suppress(Exception):
            client = await get_client()
            async for key in client.scan_iter(match="TRADE:*"):
                key_obj: str | bytes = key
                if isinstance(key_obj, str):
                    key_str = key_obj
                elif isinstance(key_obj, bytes):
                    key_str = key_obj.decode()
                else:
                    key_str = ""
                trade_id = key_str.split(":", 1)[1]
                raw = await client.get(key_str)
                if isinstance(raw, str):
                    trades[trade_id] = self._from_dict(json.loads(raw))

        if not trades:
            with contextlib.suppress(Exception):
                rows = await pg_client.fetch(
                    """
                    SELECT trade_id, signal_id, account_id, pair, direction, status, risk_mode,
                           total_risk_percent, total_risk_amount, pnl, close_reason, legs,
                           created_at, updated_at, closed_at
                    FROM trade_history
                    WHERE status NOT IN ('CANCELLED', 'CLOSED', 'SKIPPED', 'ABORTED')
                    ORDER BY updated_at DESC
                    LIMIT 500
                    """
                )
                for row in rows:
                    data = dict(row)
                    for field in ("created_at", "updated_at", "closed_at"):
                        if data.get(field) is not None:
                            data[field] = data[field].isoformat()
                    trade = self._from_dict(data)
                    trades[trade.trade_id] = trade

        return [
            t
            for t in sorted(trades.values(), key=lambda x: x.updated_at, reverse=True)
            if t.status not in {TradeStatus.CANCELLED, TradeStatus.CLOSED, TradeStatus.SKIPPED}
        ]

    async def get_all_trades_async(self) -> list[Trade]:
        """Return all trades (active + terminal) from Redis and Postgres."""
        trades: dict[str, Trade] = dict(self._memory_trades)
        with contextlib.suppress(Exception):
            client = await get_client()
            async for key in client.scan_iter(match="TRADE:*"):
                key_obj: str | bytes = key
                if isinstance(key_obj, str):
                    key_str = key_obj
                elif isinstance(key_obj, bytes):
                    key_str = key_obj.decode()
                else:
                    key_str = ""
                trade_id = key_str.split(":", 1)[1]
                raw = await client.get(key_str)
                if isinstance(raw, str):
                    trades[trade_id] = self._from_dict(json.loads(raw))

        with contextlib.suppress(Exception):
            rows = await pg_client.fetch(
                """
                SELECT trade_id, signal_id, account_id, pair, direction, status, risk_mode,
                       total_risk_percent, total_risk_amount, pnl, close_reason, legs,
                       created_at, updated_at, closed_at
                FROM trade_history
                ORDER BY updated_at DESC
                LIMIT 500
                """
            )
            for row in rows:
                data = dict(row)
                for field in ("created_at", "updated_at", "closed_at"):
                    if data.get(field) is not None:
                        data[field] = data[field].isoformat()
                trade = self._from_dict(data)
                if trade.trade_id not in trades:
                    trades[trade.trade_id] = trade

        return sorted(trades.values(), key=lambda x: x.updated_at, reverse=True)

    def _from_dict(self, data: dict[str, object]) -> Trade:
        legs_payload = data.get("legs")
        if not legs_payload or not isinstance(legs_payload, list):
            legs_payload = [
                {
                    "leg": 1,
                    "entry": float(str(data.get("entry_price") or 0.0)),
                    "sl": float(str(data.get("stop_loss") or 0.0)),
                    "tp": float(str(data.get("take_profit") or 0.0)),
                    "lot": float(str(data.get("lot_size") or 0.01)),
                    "status": str(data.get("status", "INTENDED")),
                }
            ]

        legs: list[TradeLeg] = []
        for leg in legs_payload:
            leg_dict: dict[str, object] = dict(leg) if isinstance(leg, dict) else {}
            try:
                leg_num = int(float(str(leg_dict.get("leg", 1))))
            except (ValueError, TypeError):
                leg_num = 1

            try:
                entry = float(str(leg_dict.get("entry", 0.0)))
            except (ValueError, TypeError):
                entry = 0.0

            try:
                sl = float(str(leg_dict.get("sl", 0.0)))
            except (ValueError, TypeError):
                sl = 0.0

            try:
                tp = float(str(leg_dict.get("tp", 0.0)))
            except (ValueError, TypeError):
                tp = 0.0

            try:
                lot = float(str(leg_dict.get("lot", 0.01)))
            except (ValueError, TypeError):
                lot = 0.01

            status_str = str(leg_dict.get("status", "INTENDED"))
            try:
                leg_status = TradeStatus(status_str)
            except ValueError:
                leg_status = TradeStatus.INTENDED

            legs.append(
                TradeLeg(
                    leg=leg_num,
                    entry=entry,
                    sl=sl,
                    tp=tp,
                    lot=lot,
                    status=leg_status,
                )
            )

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

        close_reason = None
        close_reason_raw = data.get("close_reason")
        if close_reason_raw is not None:
            try:
                from schemas.trade_models import CloseReason

                close_reason = CloseReason(str(close_reason_raw))
            except (ValueError, ImportError):
                close_reason = None

        return Trade(
            trade_id=str(data.get("trade_id", "")),
            signal_id=str(data.get("signal_id", "")),
            account_id=str(data.get("account_id", "")),
            pair=str(data.get("pair", "")),
            direction=str(data.get("direction", "BUY")),
            status=status,
            risk_mode=risk_mode,
            total_risk_percent=float(str(data.get("total_risk_percent", 0.1) or 0.1)),
            total_risk_amount=float(str(data.get("total_risk_amount", 0.01) or 0.01)),
            legs=legs,
            created_at=_parse_dt(data.get("created_at")),
            updated_at=_parse_dt(data.get("updated_at")),
            close_reason=close_reason,
            pnl=float(str(data["pnl"])) if data.get("pnl") is not None else None,
        )

    def _new_trade_id(self, now: datetime.datetime) -> str:
        base = int(now.timestamp() * 1000)
        trade_id = f"T-{base}"
        suffix = 1
        while trade_id in self._memory_trades:
            suffix += 1
            trade_id = f"T-{base}-{suffix}"
        return trade_id

    def _persist_trade(self, trade: Trade) -> None:
        with contextlib.suppress(Exception):
            redis_client.client.set(f"TRADE:{trade.trade_id}", trade.model_dump_json())


def _parse_dt(value: object | None) -> datetime.datetime:
    if not value:
        return datetime.datetime.now(datetime.UTC)
    value_str: str = str(value)
    if not value_str:
        return datetime.datetime.now(datetime.UTC)
    try:
        return datetime.datetime.fromisoformat(value_str.replace("Z", "+00:00"))
    except Exception:
        return datetime.datetime.now(datetime.UTC)
