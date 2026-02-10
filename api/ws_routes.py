"""
WebSocket Routes — Real-time push to frontend.

Endpoints:
  WS /ws/prices                   — Live price stream (all symbols)
  WS /ws/trades                   — Trade status change events
"""

import asyncio
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from dashboard.price_feed import PriceFeed
from dashboard.trade_ledger import TradeLedger

router = APIRouter()

# Connection manager for WebSocket clients
class ConnectionManager:
    """Manages WebSocket connections."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        """Accept and register new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
    
    def disconnect(self, websocket: WebSocket):
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
price_manager = ConnectionManager()
trade_manager = ConnectionManager()

# Service instances
_price_feed = PriceFeed()
_trade_ledger = TradeLedger()


@router.websocket("/ws/prices")
async def websocket_prices(websocket: WebSocket):
    """
    WebSocket endpoint for live price stream.
    
    Pushes price updates for all symbols every 2 seconds.
    """
    await price_manager.connect(websocket)
    logger.info("Price WebSocket client connected")
    
    try:
        # Send initial snapshot
        prices = _price_feed.get_all_prices()
        await websocket.send_json({
            "type": "snapshot",
            "data": prices,
        })
        
        # Keep connection alive and send updates
        while True:
            # Get latest prices
            prices = _price_feed.get_all_prices()
            
            # Send update
            await websocket.send_json({
                "type": "update",
                "data": prices,
            })
            
            # Wait 2 seconds before next update
            await asyncio.sleep(2)
            
    except WebSocketDisconnect:
        price_manager.disconnect(websocket)
        logger.info("Price WebSocket client disconnected")
    except Exception as exc:
        logger.error(f"Price WebSocket error: {exc}")
        price_manager.disconnect(websocket)


@router.websocket("/ws/trades")
async def websocket_trades(websocket: WebSocket):
    """
    WebSocket endpoint for trade status change events.
    
    Pushes trade updates whenever active trades change.
    """
    await trade_manager.connect(websocket)
    logger.info("Trade WebSocket client connected")
    
    try:
        # Track last known trade state
        last_trade_snapshot = {}
        
        # Send initial snapshot
        active_trades = _trade_ledger.get_active_trades()
        trades_data = [trade.model_dump() for trade in active_trades]
        
        await websocket.send_json({
            "type": "snapshot",
            "data": trades_data,
        })
        
        # Build initial snapshot
        for trade in active_trades:
            last_trade_snapshot[trade.trade_id] = trade.status.value
        
        # Keep connection alive and send updates when trades change
        while True:
            # Get current active trades
            active_trades = _trade_ledger.get_active_trades()
            current_snapshot = {
                trade.trade_id: trade.status.value
                for trade in active_trades
            }
            
            # Check for changes
            changed_trades = []
            
            # Check for status changes or new trades
            for trade in active_trades:
                last_status = last_trade_snapshot.get(trade.trade_id)
                
                if last_status != trade.status.value:
                    # Status changed or new trade
                    changed_trades.append(trade)
                    last_trade_snapshot[trade.trade_id] = trade.status.value
            
            # Check for removed trades (closed/cancelled)
            removed_trade_ids = set(last_trade_snapshot.keys()) - set(current_snapshot.keys())
            for trade_id in removed_trade_ids:
                del last_trade_snapshot[trade_id]
            
            # Send updates if any changes
            if changed_trades or removed_trade_ids:
                await websocket.send_json({
                    "type": "update",
                    "changed": [trade.model_dump() for trade in changed_trades],
                    "removed": list(removed_trade_ids),
                })
            
            # Wait 2 seconds before next check
            await asyncio.sleep(2)
            
    except WebSocketDisconnect:
        trade_manager.disconnect(websocket)
        logger.info("Trade WebSocket client disconnected")
    except Exception as exc:
        logger.error(f"Trade WebSocket error: {exc}")
        trade_manager.disconnect(websocket)
