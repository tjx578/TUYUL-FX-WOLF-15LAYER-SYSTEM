"""
WebSocket Routes - Real-time push to frontend.

Endpoints:
  WS /ws/prices?token=<jwt>       - Live tick-by-tick price stream
  WS /ws/trades?token=<jwt>       - Trade status change events (event-driven)
  WS /ws/candles?token=<jwt>      - Real-time candle aggregation stream
  WS /ws/risk?token=<jwt>         - Risk state stream (drawdown, circuit breaker)
  WS /ws/equity?token=<jwt>       - Streaming equity curve with drawdown overlay

Authentication:
  All WebSocket endpoints require a valid JWT or API key passed
  as a ``token`` query parameter.  Connections without a valid token
  are closed immediately with code 4401.

Upgrade (v2):
  - Price stream changed from 2s polling to event-driven tick push (<100ms)
  - Trade stream changed from 2s polling to event-driven diff push
  - Added candle aggregation (M1/M5/M15/H1) with real-time bar updates
  - Added risk state stream for drawdown / circuit breaker monitoring
"""

import asyncio
import time

from collections import defaultdict

import fastapi  # pyright: ignore[reportMissingImports]

from loguru import logger  # pyright: ignore[reportMissingImports]

from api.middleware.ws_auth import ws_authenticate
from dashboard.price_feed import PriceFeed
from dashboard.trade_ledger import TradeLedger

router = fastapi.APIRouter()

# Maximum concurrent WebSocket connections per manager
MAX_WS_CONNECTIONS = 50

# Tick-by-tick push interval (near real-time, batched per 100ms to avoid flood)
TICK_BATCH_INTERVAL = 0.1  # 100ms
# Trade diff check interval (event-driven with fallback poll)
TRADE_CHECK_INTERVAL = 0.25  # 250ms
# Candle update interval
CANDLE_UPDATE_INTERVAL = 0.5  # 500ms
# Risk state push interval
RISK_STATE_INTERVAL = 1.0  # 1s
# Equity curve push interval
EQUITY_PUSH_INTERVAL = 2.0  # 2s (balance/equity changes slowly)


# ---------------------------------------------------------------------------
# Candle Aggregator -- builds OHLC bars from tick stream
# ---------------------------------------------------------------------------

class CandleAggregator:
    """Builds OHLC candle bars from incoming tick data in real-time."""

    TIMEFRAMES = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}

    def __init__(self) -> None:
        # {symbol: {timeframe: {open, high, low, close, volume, ts_open, ts_close}}}
        self._bars: dict[str, dict[str, dict]] = defaultdict(dict)

    def _bar_key(self, timestamp: float, seconds: int) -> float:
        """Floor timestamp to bar open."""
        return float(int(timestamp) // seconds * seconds)

    def ingest_tick(self, symbol: str, bid: float, ask: float, ts: float) -> list[dict]:
        """
        Feed a tick into the aggregator.
        Returns list of completed bars (if any bar rolled over).
        """
        mid = round((bid + ask) / 2, 6)
        completed: list[dict] = []

        for tf_name, tf_seconds in self.TIMEFRAMES.items():
            bar_open_ts = self._bar_key(ts, tf_seconds)
            current = self._bars[symbol].get(tf_name)

            if current is None or current["ts_open"] != bar_open_ts:
                # New bar -- emit old one if exists
                if current is not None:
                    completed.append({
                        "symbol": symbol,
                        "timeframe": tf_name,
                        "bar": current,
                        "status": "closed",
                    })
                # Start new bar
                self._bars[symbol][tf_name] = {
                    "open": mid,
                    "high": mid,
                    "low": mid,
                    "close": mid,
                    "volume": 1,
                    "ts_open": bar_open_ts,
                    "ts_close": bar_open_ts + tf_seconds,
                }
            else:
                # Update existing bar
                current["high"] = max(current["high"], mid)
                current["low"] = min(current["low"], mid)
                current["close"] = mid
                current["volume"] += 1

        return completed

    def get_current_bars(self, symbol: str | None = None) -> dict:
        """Return all current (forming) bars."""
        if symbol:
            return {symbol: dict(self._bars.get(symbol, {}))}
        return {s: dict(bars) for s, bars in self._bars.items()}


_candle_agg = CandleAggregator()


# ---------------------------------------------------------------------------
# Connection Manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages WebSocket connections with authentication."""

    def __init__(self, name: str = "default"):
        self.name = name
        self.active_connections: set[fastapi.WebSocket] = set()

    async def connect(self, websocket: fastapi.WebSocket) -> bool:
        """
        Authenticate, accept, and register a new WebSocket connection.

        Returns True if connected, False if rejected.
        """
        # Enforce connection cap
        if len(self.active_connections) >= MAX_WS_CONNECTIONS:
            logger.warning(
                f"WS [{self.name}] max connections reached ({MAX_WS_CONNECTIONS}), rejecting"
            )
            await websocket.close(code=4429, reason="Too many connections")
            return False

        # Authenticate BEFORE accepting
        if not await ws_authenticate(websocket):
            return False

        await websocket.accept()
        self.active_connections.add(websocket)
        return True

    def disconnect(self, websocket: fastapi.WebSocket):
        """Remove WebSocket connection."""
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.debug(f"Failed to send to client: {exc}")
                disconnected.add(connection)

        # Remove disconnected clients
        self.active_connections -= disconnected


# Create connection managers
price_manager = ConnectionManager(name="prices")
trade_manager = ConnectionManager(name="trades")
candle_manager = ConnectionManager(name="candles")
risk_manager = ConnectionManager(name="risk")
equity_manager = ConnectionManager(name="equity")

# Service instances
_price_feed = PriceFeed()
_trade_ledger = TradeLedger()


# ---------------------------------------------------------------------------
# WS /ws/prices -- Tick-by-tick price stream
# ---------------------------------------------------------------------------

@router.websocket("/ws/prices")
async def websocket_prices(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for live tick-by-tick price stream.

    Requires ``?token=<jwt_or_api_key>`` query parameter.
    Pushes price changes as soon as they are detected (~100ms batches).
    """
    connected = await price_manager.connect(websocket)
    if not connected:
        return
    logger.info("Price WebSocket client connected (tick-by-tick)")

    try:
        # Send initial snapshot
        prices = _price_feed.get_all_prices()
        await websocket.send_json({"type": "snapshot", "data": prices})

        # Track last known prices to push only diffs
        last_prices: dict[str, dict] = dict(prices) if prices else {}

        while True:
            current = _price_feed.get_all_prices() or {}
            changed: dict[str, dict] = {}

            for symbol, price_data in current.items():
                prev = last_prices.get(symbol)
                if prev is None or prev.get("bid") != price_data.get("bid") or prev.get("ask") != price_data.get("ask"):
                    changed[symbol] = price_data
                    last_prices[symbol] = price_data

                    # Feed tick into candle aggregator
                    _candle_agg.ingest_tick(
                        symbol,
                        float(price_data.get("bid", 0)),
                        float(price_data.get("ask", 0)),
                        float(price_data.get("ts", time.time())),
                    )

            if changed:
                await websocket.send_json({
                    "type": "tick",
                    "data": changed,
                    "ts": time.time(),
                })

            # ~100ms batch interval for near-real-time without flooding
            await asyncio.sleep(TICK_BATCH_INTERVAL)

    except fastapi.WebSocketDisconnect:
        price_manager.disconnect(websocket)
        logger.info("Price WebSocket client disconnected")
    except Exception as exc:
        logger.error(f"Price WebSocket error: {exc}")
        price_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# WS /ws/trades -- Event-driven trade updates
# ---------------------------------------------------------------------------

@router.websocket("/ws/trades")
async def websocket_trades(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for trade status change events.

    Requires ``?token=<jwt_or_api_key>`` query parameter.
    Pushes trade updates as soon as state changes are detected (~250ms check).
    """
    connected = await trade_manager.connect(websocket)
    if not connected:
        return
    logger.info("Trade WebSocket client connected (event-driven)")

    try:
        # Track last known trade state
        last_trade_snapshot: dict[str, str] = {}

        # Send initial snapshot
        active_trades = _trade_ledger.get_active_trades()
        trades_data = [trade.model_dump() for trade in active_trades]

        await websocket.send_json({"type": "snapshot", "data": trades_data})

        # Build initial snapshot
        for trade in active_trades:
            last_trade_snapshot[trade.trade_id] = trade.status.value

        while True:
            active_trades = _trade_ledger.get_active_trades()
            current_snapshot = {t.trade_id: t.status.value for t in active_trades}

            changed_trades = []
            for trade in active_trades:
                last_status = last_trade_snapshot.get(trade.trade_id)
                if last_status != trade.status.value:
                    changed_trades.append(trade)
                    last_trade_snapshot[trade.trade_id] = trade.status.value

            removed_trade_ids = set(last_trade_snapshot.keys()) - set(current_snapshot.keys())
            for trade_id in removed_trade_ids:
                del last_trade_snapshot[trade_id]

            if changed_trades or removed_trade_ids:
                await websocket.send_json({
                    "type": "update",
                    "changed": [t.model_dump() for t in changed_trades],
                    "removed": list(removed_trade_ids),
                    "ts": time.time(),
                })

            # 250ms for near-instant trade event delivery
            await asyncio.sleep(TRADE_CHECK_INTERVAL)

    except fastapi.WebSocketDisconnect:
        trade_manager.disconnect(websocket)
        logger.info("Trade WebSocket client disconnected")
    except Exception as exc:
        logger.error(f"Trade WebSocket error: {exc}")
        trade_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# WS /ws/candles -- Real-time candle bar stream
# ---------------------------------------------------------------------------

@router.websocket("/ws/candles")
async def websocket_candles(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for real-time OHLC candle updates.

    Pushes forming bars every 500ms and closed bar events.
    Query params: ?token=<jwt>&symbol=<EURUSD> (optional symbol filter)
    """
    connected = await candle_manager.connect(websocket)
    if not connected:
        return

    # Optional symbol filter
    symbol_filter = websocket.query_params.get("symbol")
    logger.info(f"Candle WebSocket connected (filter={symbol_filter or 'all'})")

    try:
        # Send current bars snapshot
        bars = _candle_agg.get_current_bars(symbol_filter)
        await websocket.send_json({"type": "snapshot", "data": bars})

        while True:
            bars = _candle_agg.get_current_bars(symbol_filter)
            await websocket.send_json({
                "type": "forming",
                "data": bars,
                "ts": time.time(),
            })
            await asyncio.sleep(CANDLE_UPDATE_INTERVAL)

    except fastapi.WebSocketDisconnect:
        candle_manager.disconnect(websocket)
        logger.info("Candle WebSocket client disconnected")
    except Exception as exc:
        logger.error(f"Candle WebSocket error: {exc}")
        candle_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# WS /ws/risk -- Risk state stream
# ---------------------------------------------------------------------------

@router.websocket("/ws/risk")
async def websocket_risk(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for risk state monitoring.

    Pushes drawdown, circuit breaker, and prop firm guard state every 1s.
    """
    connected = await risk_manager.connect(websocket)
    if not connected:
        return
    logger.info("Risk WebSocket client connected")

    try:
        while True:
            # Build risk state from available modules
            risk_state: dict = {"ts": time.time()}

            try:
                from risk.risk_manager import RiskManager  # noqa: PLC0415
                rm = RiskManager() # pyright: ignore[reportCallIssue]
                snapshot = rm.get_risk_snapshot()
                risk_state["risk_snapshot"] = snapshot
            except Exception:
                risk_state["risk_snapshot"] = None

            try:
                from risk.circuit_breaker import CircuitBreaker  # noqa: PLC0415
                cb = CircuitBreaker() # pyright: ignore[reportCallIssue]
                risk_state["circuit_breaker"] = {
                    "state": cb.state.value if hasattr(cb, "state") else "UNKNOWN", # pyright: ignore[reportAttributeAccessIssue]
                    "is_open": cb.is_open() if hasattr(cb, "is_open") else False, # pyright: ignore[reportAttributeAccessIssue]
                }
            except Exception:
                risk_state["circuit_breaker"] = None

            try:
                from risk.drawdown import (  # noqa: PLC0415
                    DrawdownTracker,  # pyright: ignore[reportAttributeAccessIssue]
                )
                dd = DrawdownTracker()
                risk_state["drawdown"] = dd.get_status() if hasattr(dd, "get_status") else None
            except Exception:
                risk_state["drawdown"] = None

            await websocket.send_json({"type": "risk_state", "data": risk_state})
            await asyncio.sleep(RISK_STATE_INTERVAL)

    except fastapi.WebSocketDisconnect:
        risk_manager.disconnect(websocket)
        logger.info("Risk WebSocket client disconnected")
    except Exception as exc:
        logger.error(f"Risk WebSocket error: {exc}")
        risk_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# WS /ws/equity -- Streaming equity curve with drawdown overlay
# ---------------------------------------------------------------------------

# In-memory equity history buffer (ring buffer, max 1440 points = 24h at 1min)
_EQUITY_HISTORY_MAX = 1440
_equity_history: list[dict] = []


def _compute_drawdown(equity: float, peak: float) -> float:
    """Compute drawdown percentage from peak equity."""
    if peak <= 0:
        return 0.0
    return round((peak - equity) / peak * 100.0, 4)


@router.websocket("/ws/equity")
async def websocket_equity(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for streaming equity curve with drawdown overlay.

    Pushes equity snapshots every 2s containing:
    - equity, balance, floating_pnl
    - drawdown_pct, peak_equity
    - equity_history (ring buffer of recent points)

    Requires ``?token=<jwt_or_api_key>`` query parameter.
    Optional ``?account_id=<id>`` to filter to specific account.
    """
    connected = await equity_manager.connect(websocket)
    if not connected:
        return

    account_filter = websocket.query_params.get("account_id")
    logger.info(f"Equity WebSocket connected (account={account_filter or 'default'})")

    peak_equity: float = 0.0
    last_equity: float | None = None

    try:
        # Send initial snapshot with history
        await websocket.send_json({
            "type": "equity_snapshot",
            "data": {
                "history": list(_equity_history),
                "ts": time.time(),
            },
        })

        while True:
            # Fetch current account state
            equity_point: dict = {"ts": time.time()}

            try:
                from dashboard.account_manager import AccountManager  # noqa: PLC0415
                am = AccountManager()
                accounts = am.list_accounts()

                if account_filter:
                    account = am.get_account(account_filter)
                    accounts = [account] if account else []

                if accounts:
                    # Use first/filtered account
                    acct = accounts[0]
                    equity = float(acct.equity)
                    balance = float(acct.balance)
                    floating_pnl = round(equity - balance, 2)

                    # Track peak for drawdown calculation
                    peak_equity = max(peak_equity, equity)

                    dd_pct = _compute_drawdown(equity, peak_equity)

                    equity_point.update({
                        "account_id": acct.account_id,
                        "equity": equity,
                        "balance": balance,
                        "floating_pnl": floating_pnl,
                        "peak_equity": peak_equity,
                        "drawdown_pct": dd_pct,
                    })
                else:
                    equity_point.update({
                        "equity": 0.0,
                        "balance": 0.0,
                        "floating_pnl": 0.0,
                        "peak_equity": 0.0,
                        "drawdown_pct": 0.0,
                    })

            except Exception as exc:
                logger.debug(f"Equity fetch failed: {exc}")
                equity_point.update({
                    "equity": 0.0,
                    "balance": 0.0,
                    "floating_pnl": 0.0,
                    "peak_equity": 0.0,
                    "drawdown_pct": 0.0,
                    "error": str(exc),
                })

            current_equity = equity_point.get("equity", 0.0)

            # Only append to history if equity changed (avoid flat duplicates)
            if last_equity is None or current_equity != last_equity:
                _equity_history.append(equity_point)
                if len(_equity_history) > _EQUITY_HISTORY_MAX:
                    _equity_history.pop(0)
                last_equity = current_equity

            # Push update to client
            await websocket.send_json({
                "type": "equity_update",
                "data": equity_point,
            })

            await asyncio.sleep(EQUITY_PUSH_INTERVAL)

    except fastapi.WebSocketDisconnect:
        equity_manager.disconnect(websocket)
        logger.info("Equity WebSocket client disconnected")
    except Exception as exc:
        logger.error(f"Equity WebSocket error: {exc}")
        equity_manager.disconnect(websocket)
