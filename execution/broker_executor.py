"""
Broker executor — dumb execution layer. No market analysis.
Only places, monitors, and reports order status.
All decisions come from constitution + dashboard.
"""

from __future__ import annotations

import time

from dataclasses import dataclass
from enum import Enum


class OrderAction(Enum):
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"
    BUY_MARKET = "BUY_MARKET"
    SELL_MARKET = "SELL_MARKET"


@dataclass
class ExecutionRequest:
    """Comes from dashboard/constitution. Executor does NOT modify these."""
    signal_id: str
    symbol: str
    action: OrderAction
    lot_size: float
    entry_price: float
    stop_loss: float
    take_profit: float
    expiry_seconds: float | None = None
    magic_number: int = 151515
    comment: str = "TUYUL-FX"


@dataclass
class ExecutionResult:
    signal_id: str
    success: bool
    broker_ticket: int | None = None
    fill_price: float | None = None
    slippage_pips: float | None = None
    error_code: int | None = None
    error_message: str | None = None
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def has_slippage(self) -> bool:
        return self.slippage_pips is not None and abs(self.slippage_pips) > 0.5


class MT5Executor:
    """
    Dumb executor for MetaTrader5.
    NO market analysis. NO decision-making. NO overrides.
    Only: place order → report result.
    """

    def __init__(self):
        self._mt5 = None

    def _ensure_mt5(self):
        if self._mt5 is None:
            import MetaTrader5 as mt5  # pyright: ignore[reportMissingImports] # noqa: N813, PLC0415
            self._mt5 = mt5

    def place_order(self, request: ExecutionRequest) -> ExecutionResult:
        """
        Place a single order. Returns execution result.
        This function has ZERO intelligence — it does exactly what is asked.
        """
        self._ensure_mt5()
        mt5 = self._mt5

        # Map action to MT5 order type
        type_map = {
            OrderAction.BUY_LIMIT: mt5.ORDER_TYPE_BUY_LIMIT, # type: ignore
            OrderAction.SELL_LIMIT: mt5.ORDER_TYPE_SELL_LIMIT, # pyright: ignore[reportOptionalMemberAccess]
            OrderAction.BUY_STOP: mt5.ORDER_TYPE_BUY_STOP, # pyright: ignore[reportOptionalMemberAccess]
            OrderAction.SELL_STOP: mt5.ORDER_TYPE_SELL_STOP, # pyright: ignore[reportOptionalMemberAccess]
            OrderAction.BUY_MARKET: mt5.ORDER_TYPE_BUY, # pyright: ignore[reportOptionalMemberAccess]
            OrderAction.SELL_MARKET: mt5.ORDER_TYPE_SELL, # pyright: ignore[reportOptionalMemberAccess]
        }

        order_type = type_map.get(request.action)
        if order_type is None:
            return ExecutionResult(
                signal_id=request.signal_id,
                success=False,
                error_code=-1,
                error_message=f"Unknown action: {request.action}",
            )

        # Build MT5 request
        mt5_request = {
            "action": mt5.TRADE_ACTION_DEAL if "MARKET" in request.action.value else mt5.TRADE_ACTION_PENDING, # pyright: ignore[reportOptionalMemberAccess]
            "symbol": request.symbol,
            "volume": request.lot_size,
            "type": order_type,
            "price": request.entry_price,
            "sl": request.stop_loss,
            "tp": request.take_profit,
            "magic": request.magic_number,
            "comment": request.comment,
            "type_time": mt5.ORDER_TIME_GTC, # pyright: ignore[reportOptionalMemberAccess]
            "type_filling": mt5.ORDER_FILLING_IOC, # pyright: ignore[reportOptionalMemberAccess]
        }

        # Pre-flight: check symbol exists and is tradeable
        symbol_info = mt5.symbol_info(request.symbol) # pyright: ignore[reportOptionalMemberAccess]
        if symbol_info is None:
            return ExecutionResult(
                signal_id=request.signal_id,
                success=False,
                error_code=-2,
                error_message=f"Symbol {request.symbol} not found",
            )

        if not symbol_info.visible:
            mt5.symbol_select(request.symbol, True) # pyright: ignore[reportOptionalMemberAccess]

        # Execute
        result = mt5.order_send(mt5_request) # pyright: ignore[reportOptionalMemberAccess]

        if result is None:
            return ExecutionResult(
                signal_id=request.signal_id,
                success=False,
                error_code=mt5.last_error()[0], # pyright: ignore[reportOptionalMemberAccess]
                error_message=mt5.last_error()[1], # pyright: ignore[reportOptionalMemberAccess]
            )

        if result.retcode != mt5.TRADE_RETCODE_DONE: # pyright: ignore[reportOptionalMemberAccess]
            return ExecutionResult(
                signal_id=request.signal_id,
                success=False,
                error_code=result.retcode,
                error_message=result.comment,
            )

        # Calculate slippage
        slippage = None
        if result.price and request.entry_price:
            point = symbol_info.point
            if point > 0:
                slippage = abs(result.price - request.entry_price) / point / 10

        return ExecutionResult(
            signal_id=request.signal_id,
            success=True,
            broker_ticket=result.order,
            fill_price=result.price,
            slippage_pips=slippage,
        )

    def cancel_pending(self, ticket: int) -> ExecutionResult:
        """Cancel a pending order by ticket number."""
        self._ensure_mt5()
        mt5 = self._mt5

        request = {
            "action": mt5.TRADE_ACTION_REMOVE, # pyright: ignore[reportOptionalMemberAccess]
            "order": ticket,
        }
        result = mt5.order_send(request) # pyright: ignore[reportOptionalMemberAccess]

        if result and result.retcode == mt5.TRADE_RETCODE_DONE: # pyright: ignore[reportOptionalMemberAccess]
            return ExecutionResult(
                signal_id="",
                success=True,
                broker_ticket=ticket,
            )
        return ExecutionResult(
            signal_id="",
            success=False,
            broker_ticket=ticket,
            error_code=result.retcode if result else -1,
            error_message=result.comment if result else "order_send returned None",
        )

    def get_open_positions(self, magic: int = 151515) -> list[dict]:
        """Get all open positions for our magic number."""
        self._ensure_mt5()
        mt5 = self._mt5

        positions = mt5.positions_get() # pyright: ignore[reportOptionalMemberAccess]
        if positions is None:
            return []

        return [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if p.type == 0 else "SELL",
                "volume": p.volume,
                "open_price": p.price_open,
                "current_price": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "swap": p.swap,
                "magic": p.magic,
                "comment": p.comment,
            }
            for p in positions
            if p.magic == magic
        ]
