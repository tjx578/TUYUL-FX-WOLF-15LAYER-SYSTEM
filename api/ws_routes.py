"""
WebSocket Routes - Real-time push to frontend.

Endpoints:
  WS /ws?token=<jwt>              - General-purpose signal relay (Redis PubSub)
  WS /ws/prices?token=<jwt>       - Live tick-by-tick price stream
  WS /ws/trades?token=<jwt>       - Trade status change events (event-driven)
  WS /ws/candles?token=<jwt>      - Real-time candle aggregation stream
  WS /ws/risk?token=<jwt>         - Risk state stream (drawdown, circuit breaker)
  WS /ws/equity?token=<jwt>       - Streaming equity curve with drawdown overlay
    WS /ws/verdict?token=<jwt>      - L12 verdict stream (event-driven + fallback)
    WS /ws/signals?token=<jwt>      - Frozen signal stream (event-driven + fallback)
    WS /ws/pipeline?token=<jwt>     - Pipeline panel stream (event-driven + fallback)

Authentication:
  All WebSocket endpoints require a valid JWT or API key passed
  as a ``token`` query parameter.  Connections without a valid token
  are closed immediately with code 4401.

Upgrade (v3):
  - Price stream: event-driven via asyncio.Event (no polling sleep)
  - Risk WS: singleton instances cached (no per-push instantiation)
  - Heartbeat: server-side ping every 30s, detects dead connections
  - Message buffer: ring-buffer per manager for replay on reconnect
  - Trade stream: event-driven diff push with 250ms fallback
  - Candle aggregation (M1/M5/M15/H1) with real-time bar updates
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import itertools
import json
import os
import time
import uuid as _uuid
from collections import deque
from collections.abc import Mapping
from typing import Any, cast

import fastapi
from loguru import logger
from redis.asyncio.client import PubSub as _AsyncPubSub

from accounts.account_manager import AccountManager
from allocation.signal_service import SIGNAL_READY_CHANNEL, SignalService
from config_loader import load_pairs
from infrastructure.redis_client import get_client as _get_async_redis_client
from state.pubsub_channels import RISK_EVENTS
from storage.l12_cache import VERDICT_READY_CHANNEL, get_verdict_async
from storage.price_feed import PriceFeed
from storage.redis_client import redis_client
from storage.trade_ledger import TradeLedger

from .middleware.ws_auth import ws_auth_guard

router = fastapi.APIRouter()

# ---------------------------------------------------------------------------
# Versioned event envelope — standard contract for all WS messages
# ---------------------------------------------------------------------------

WS_EVENT_VERSION = "1.0"


def _ws_event(
    event_type: str,
    payload: dict[str, object],
    *,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Build a versioned WS event envelope.

    Standard fields:
      event_version, event_id, event_type, server_ts, trace_id, payload
    """
    return {
        "event_version": WS_EVENT_VERSION,
        "event_id": _uuid.uuid4().hex,
        "event_type": event_type,
        "server_ts": time.time(),
        "trace_id": trace_id or _uuid.uuid4().hex[:16],
        "payload": payload,
    }


_GATE_LABELS: dict[str, str] = {
    "gate_1_tii": "TII Sym",
    "gate_2_integrity": "Integrity",
    "gate_3_rr": "R:R",
    "gate_4_fta": "FTA",
    "gate_5_montecarlo": "MC WR",
    "gate_6_propfirm": "PropFirm",
    "gate_7_drawdown": "DD",
    "gate_8_latency": "Latency",
    "gate_9_conf12": "Conf",
}

_LAYER_DEFS: list[dict[str, str]] = [
    {"id": "L1", "name": "Context", "zone": "COG"},
    {"id": "L2", "name": "MTA", "zone": "COG"},
    {"id": "L3", "name": "Technical", "zone": "ANA"},
    {"id": "L4", "name": "Scoring", "zone": "ANA"},
    {"id": "L5", "name": "Psychology", "zone": "META"},
    {"id": "L6", "name": "Risk", "zone": "META"},
    {"id": "L7", "name": "Monte Carlo", "zone": "ANA"},
    {"id": "L8", "name": "TII", "zone": "ANA"},
    {"id": "L9", "name": "SMC/VP", "zone": "ANA"},
    {"id": "L10", "name": "Position", "zone": "EXEC"},
    {"id": "L11", "name": "Execution", "zone": "EXEC"},
    {"id": "L12", "name": "Verdict", "zone": "VER"},
    {"id": "L13", "name": "Reflect", "zone": "POST"},
    {"id": "L14", "name": "Export", "zone": "POST"},
    {"id": "L15", "name": "Sovereign", "zone": "POST"},
]


def _build_pipeline_data(pair: str, verdict_data: dict[str, Any]) -> dict[str, Any]:
    """Transform cached L12 verdict data into PipelineData UI shape."""
    gates_raw: dict[str, Any] = cast(dict[str, Any], verdict_data.get("gates", {}))
    scores: dict[str, Any] = cast(dict[str, Any], verdict_data.get("scores", {}))
    execution: dict[str, Any] = cast(dict[str, Any], verdict_data.get("execution", {}))
    layers_raw: dict[str, Any] = cast(dict[str, Any], verdict_data.get("layers", {}))

    verdict_str = str(verdict_data.get("verdict", "UNKNOWN"))
    confidence = verdict_data.get("confidence", 0)
    if isinstance(confidence, str):
        conf_map = {"LOW": 0.25, "MEDIUM": 0.50, "HIGH": 0.75, "VERY_HIGH": 0.95}
        confidence_num = conf_map.get(confidence.upper(), 0.5)
    else:
        confidence_num = float(confidence)

    wolf_status = str(verdict_data.get("wolf_status", "—"))
    latency = int(
        cast(dict[str, Any], verdict_data.get("system", {})).get("latency_ms", 0)
        or gates_raw.get("gate_8_latency_val", 0)
    )

    gate_list: list[dict[str, Any]] = []
    for key, label in _GATE_LABELS.items():
        gate_val = gates_raw.get(key)
        passed = gate_val == "PASS" if isinstance(gate_val, str) else bool(gate_val)
        gate_list.append({"name": label, "val": gate_val if gate_val is not None else "—", "thr": "—", "pass": passed})

    layer_score_map: dict[str, tuple[str, str]] = {
        "L7": (str(layers_raw.get("L7_monte_carlo_win", "—")), "MC"),
        "L8": (str(scores.get("tii", layers_raw.get("L8_tii_sym", "—"))), "integ"),
        "L12": (
            f"{gates_raw.get('passed', '?')}/{gates_raw.get('total', '?')}",
            verdict_str.split("_")[0] if "_" in verdict_str else verdict_str,
        ),
    }

    pass_count = int(gates_raw.get("passed", 0))
    total_gates = int(gates_raw.get("total", 9))

    # Build set of layers that actually executed (from execution_map.layers_executed).
    # When present, layers absent from this set are marked "skip" instead of "pass".
    _exec_map_raw = verdict_data.get("execution_map")
    _exec_layers_list = (_exec_map_raw or {}).get("layers_executed", []) if isinstance(_exec_map_raw, dict) else []
    layers_executed_set: set[str] = (
        {str(lyr) for lyr in _exec_layers_list} if isinstance(_exec_layers_list, list) else set()
    )

    # Gate keys that directly reflect a specific layer's outcome
    _gate_layer_map: dict[str, str] = {
        "L4": "gate_4_fta",
        "L6": "gate_7_drawdown",
        "L7": "gate_5_montecarlo",
        "L8": "gate_1_tii",
        "L11": "gate_3_rr",
    }

    layer_list: list[dict[str, str]] = []
    for ldef in _LAYER_DEFS:
        lid = ldef["id"]
        val, detail = layer_score_map.get(lid, ("—", "—"))
        if lid == "L12":
            status = "pass" if pass_count == total_gates else ("warn" if pass_count >= 7 else "fail")
        elif lid in _gate_layer_map:
            gate_key = _gate_layer_map[lid]
            gate_val = gates_raw.get(gate_key)
            if gate_val == "FAIL":
                status = "fail"
            elif gate_val == "PASS":
                status = "pass"
            elif layers_executed_set and lid not in layers_executed_set:
                status = "skip"
            else:
                status = "pass"
        elif layers_executed_set and lid not in layers_executed_set:
            status = "skip"
        else:
            status = "pass"
        layer_list.append(
            {
                "id": lid,
                "name": ldef["name"],
                "zone": ldef["zone"],
                "status": status,
                "val": val,
                "detail": detail,
            }
        )

    entry = {
        "price": execution.get("entry_price", 0),
        "sl": execution.get("stop_loss", 0),
        "tp1": execution.get("take_profit_1", 0),
        "tp2": execution.get("take_profit_2"),
        "rr": str(execution.get("rr_ratio", "—")),
        "lots": execution.get("lot_size", 0),
        "risk$": execution.get("risk_amount", 0),
        "reward$": execution.get("reward_amount", 0),
    }

    execution_map_raw = verdict_data.get("execution_map")
    execution_map: dict[str, Any]
    if isinstance(execution_map_raw, dict):
        raw_map = cast(Mapping[Any, Any], execution_map_raw)
        execution_map = {str(k): v for k, v in raw_map.items()}
    else:
        execution_map = {
            "pair": pair,
            "timestamp": verdict_data.get("timestamp", ""),
            "layers_executed": [layer["id"] for layer in layer_list],
            "engines_invoked": [],
            "halt_reason": None,
            "constitutional_verdict": verdict_str,
        }

    return {
        "pair": pair,
        "verdict": verdict_str,
        "wolfGrade": wolf_status,
        "confidence": round(confidence_num, 4),
        "latency": latency,
        "layers": layer_list,
        "gates": gate_list,
        "entry": entry,
        "execution_map": execution_map,
        "observability": {
            "signal_conditioning": cast(dict[str, Any], verdict_data.get("system", {})).get("signal_conditioning", {}),
        },
    }


# Maximum concurrent WebSocket connections per manager
MAX_WS_CONNECTIONS = int(os.getenv("WS_MAX_CONNECTIONS", "50"))
# Deprecated: auth is now always enforced regardless of this flag.
WS_REQUIRE_AUTH = os.getenv("WS_REQUIRE_AUTH", "true").strip().lower() in {"1", "true", "yes", "on"}
if not WS_REQUIRE_AUTH:
    logger.warning(
        "WS_REQUIRE_AUTH=false is deprecated and ignored. WebSocket auth is now always enforced. Remove this env var."
    )

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
VERDICT_FALLBACK_INTERVAL = 0.5  # 500ms fallback scan if pubsub event is missed
SIGNAL_FALLBACK_INTERVAL = 0.5  # 500ms fallback scan if pubsub event is missed
PIPELINE_FALLBACK_INTERVAL = 0.5  # 500ms fallback scan if pubsub event is missed

# Heartbeat / ping interval
WS_PING_INTERVAL = float(os.getenv("WS_PING_INTERVAL", "15"))
WS_HEARTBEAT_TIMEOUT = float(os.getenv("WS_HEARTBEAT_TIMEOUT", "30"))
WS_PONG_TIMEOUT = float(os.getenv("WS_PONG_TIMEOUT", "10"))  # send timeout

# Message replay buffer size per manager
MESSAGE_BUFFER_SIZE = 100  # last N messages kept for replay on reconnect


# ---------------------------------------------------------------------------
# Candle Aggregator — replaced by HybridCandleAggregator (Dual-Zone SSOT v5)
# ---------------------------------------------------------------------------

from api.hybrid_candle_agg import HybridCandleAggregator  # noqa: E402

_candle_agg = HybridCandleAggregator()


# ---------------------------------------------------------------------------
# Connection Manager with heartbeat + message buffer
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manages WebSocket connections with authentication, heartbeat, and replay buffer."""

    def __init__(self, name: str = "default", buffer_size: int = MESSAGE_BUFFER_SIZE):
        super().__init__()
        self.name = name
        self.active_connections: set[fastapi.WebSocket] = set()
        self._ping_tasks: dict[fastapi.WebSocket, asyncio.Task[None]] = {}
        self._recv_tasks: dict[fastapi.WebSocket, asyncio.Task[None]] = {}
        self._last_heartbeat: dict[fastapi.WebSocket, float] = {}
        self._session_keys: dict[fastapi.WebSocket, str] = {}
        # Per-connection send lock — prevents concurrent send_json calls
        # (heartbeat ping vs endpoint data push) from corrupting the WS frame.
        self._send_locks: dict[fastapi.WebSocket, asyncio.Lock] = {}
        # Ring buffer of recent messages for replay on reconnect
        self._message_buffer: deque[dict[str, object]] = deque(maxlen=buffer_size)
        # Per-connection sequence counters — each client gets its own monotonic
        # counter so send_stamped() to one client doesn't create gaps for another.
        self._per_conn_seq: dict[fastapi.WebSocket, itertools.count[int]] = {}
        # Global buffer ordering counter (not sent to clients)
        self._buffer_seq = itertools.count(1)

    async def connect(self, websocket: fastapi.WebSocket) -> bool:
        """
        Authenticate, accept, and register a new WebSocket connection.

        Returns True if connected, False if rejected.
        """
        # Enforce connection cap
        if len(self.active_connections) >= MAX_WS_CONNECTIONS:
            logger.warning(f"WS [{self.name}] max connections reached ({MAX_WS_CONNECTIONS}), rejecting")
            await websocket.close(code=4429, reason="Too many connections")
            return False

        # Authenticate BEFORE accepting — always enforced
        raw_user = await ws_auth_guard(websocket)
        if not raw_user:
            return False
        user = cast(Mapping[str, Any], raw_user)

        await websocket.accept()
        self.active_connections.add(websocket)
        self._last_heartbeat[websocket] = time.time()
        self._send_locks[websocket] = asyncio.Lock()
        self._per_conn_seq[websocket] = itertools.count(1)
        self._register_session(websocket, user)

        # Start heartbeat ping task for this connection
        self._ping_tasks[websocket] = asyncio.create_task(self._heartbeat_loop(websocket))
        self._recv_tasks[websocket] = asyncio.create_task(self._receive_loop(websocket))

        return True

    def disconnect(self, websocket: fastapi.WebSocket):
        """Remove WebSocket connection and cancel its heartbeat."""
        self.active_connections.discard(websocket)
        self._last_heartbeat.pop(websocket, None)
        self._send_locks.pop(websocket, None)
        self._per_conn_seq.pop(websocket, None)
        self._unregister_session(websocket)
        task = self._ping_tasks.pop(websocket, None)
        if task and not task.done():
            task.cancel()
        recv_task = self._recv_tasks.pop(websocket, None)
        if recv_task and not recv_task.done():
            recv_task.cancel()

    async def _receive_loop(self, websocket: fastapi.WebSocket) -> None:
        """Consume inbound frames to track heartbeat acknowledgements."""
        try:
            while websocket in self.active_connections:
                message = await websocket.receive_text()
                payload: dict[str, Any] | None = None
                with contextlib.suppress(Exception):
                    parsed = json.loads(message)
                    if isinstance(parsed, dict):
                        payload = cast(dict[str, Any], parsed)

                raw_type: Any = payload.get("type", "") if payload is not None else ""
                msg_type = raw_type.lower() if isinstance(raw_type, str) else ""
                if msg_type in {"pong", "heartbeat", "ping"}:
                    self._last_heartbeat[websocket] = time.time()
                    self._touch_session(websocket)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug(f"WS [{self.name}] receive loop ended")
            self.disconnect(websocket)

    async def _heartbeat_loop(self, websocket: fastapi.WebSocket) -> None:
        """Send periodic ping frames to detect dead connections behind NAT/proxy."""
        try:
            while websocket in self.active_connections:
                await asyncio.sleep(WS_PING_INTERVAL)

                token_exp = int(getattr(websocket.state, "auth_exp", 0) or 0)
                if token_exp and int(time.time()) >= token_exp:
                    logger.info(f"WS [{self.name}] token expired, disconnecting client")
                    self.disconnect(websocket)
                    with contextlib.suppress(Exception):
                        await websocket.close(code=4401, reason="Token expired")
                    break

                last_seen = self._last_heartbeat.get(websocket, 0.0)
                if last_seen and (time.time() - last_seen) > WS_HEARTBEAT_TIMEOUT:
                    logger.info(f"WS [{self.name}] heartbeat stale, disconnecting client")
                    self.disconnect(websocket)
                    with contextlib.suppress(Exception):
                        await websocket.close(code=4408, reason="Heartbeat timeout")
                    break

                try:
                    lock = self._send_locks.get(websocket)
                    ping_payload = {"type": "ping", "ts": time.time()}
                    if lock:
                        async with lock:
                            await asyncio.wait_for(
                                websocket.send_json(ping_payload),
                                timeout=WS_PONG_TIMEOUT,
                            )
                    else:
                        await asyncio.wait_for(
                            websocket.send_json(ping_payload),
                            timeout=WS_PONG_TIMEOUT,
                        )
                    # Successful send proves the connection is at least half-alive.
                    # Reset heartbeat so staleness only triggers after *two* missed
                    # ping/pong cycles (send succeeds but no pong comes back).
                    self._last_heartbeat[websocket] = time.time()
                    self._touch_session(websocket)
                except (TimeoutError, Exception):
                    logger.info(f"WS [{self.name}] heartbeat failed, disconnecting client")
                    self.disconnect(websocket)
                    with contextlib.suppress(Exception):
                        await websocket.close(code=4408, reason="Heartbeat timeout")
                    break
        except asyncio.CancelledError:
            pass

    def _register_session(self, websocket: fastapi.WebSocket, user: Mapping[str, Any] | None) -> None:
        user_id = str((user or {}).get("sub") or getattr(websocket.state, "user", "anonymous"))
        key = f"ws:sessions:user_{user_id}:{id(websocket)}"
        self._session_keys[websocket] = key
        with contextlib.suppress(Exception):
            redis_client.client.set(key, int(time.time()), ex=max(int(WS_HEARTBEAT_TIMEOUT * 2), 30))

    def _touch_session(self, websocket: fastapi.WebSocket) -> None:
        key = self._session_keys.get(websocket)
        if not key:
            return
        with contextlib.suppress(Exception):
            redis_client.client.set(key, int(time.time()), ex=max(int(WS_HEARTBEAT_TIMEOUT * 2), 30))

    def _unregister_session(self, websocket: fastapi.WebSocket) -> None:
        key = self._session_keys.pop(websocket, None)
        if not key:
            return
        with contextlib.suppress(Exception):
            redis_client.client.delete(key)

    def buffer_message(self, message: dict[str, Any]) -> None:
        """Store message in replay buffer."""
        self._message_buffer.append(message)

    async def replay_buffer(
        self,
        websocket: fastapi.WebSocket,
        since_ts: float | None = None,
        since_seq: int | None = None,
    ) -> None:
        """
        Replay buffered messages to a reconnecting client.

        Args:
            websocket: The reconnected client.
            since_ts: Only replay messages after this timestamp. If None, replay all.
            since_seq: Only replay messages with seq > since_seq (preferred over since_ts).
        """
        conn_counter = self._per_conn_seq.get(websocket)
        if conn_counter is None:
            return

        replayed = 0
        for msg in self._message_buffer:
            # Prefer seq-based filtering using buffer ordering seq
            if since_seq is not None:
                msg_buf_seq = msg.get("_buf_seq", 0)
                if isinstance(msg_buf_seq, int) and msg_buf_seq <= since_seq:
                    continue
            elif since_ts is not None:
                msg_ts_raw = msg.get("ts", 0.0)
                msg_ts = float(msg_ts_raw) if isinstance(msg_ts_raw, int | float) else 0.0
                if msg_ts <= since_ts:
                    continue
            try:
                replay_msg = {**msg, "seq": next(conn_counter)}
                lock = self._send_locks.get(websocket)
                if lock:
                    async with lock:
                        await websocket.send_json(replay_msg)
                else:
                    await websocket.send_json(replay_msg)
                replayed += 1
            except Exception:
                break
        if replayed > 0:
            logger.debug(f"WS [{self.name}] replayed {replayed} buffered messages")

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all connected clients and buffer it.

        Each client receives its own per-connection ``seq`` so that
        ``send_stamped()`` to one client does not create gaps for another.
        """
        message["_buf_seq"] = next(self._buffer_seq)
        self.buffer_message(message)
        disconnected: set[fastapi.WebSocket] = set()

        for connection in self.active_connections:
            try:
                conn_counter = self._per_conn_seq.get(connection)
                if conn_counter is None:
                    continue
                msg_copy = {**message, "seq": next(conn_counter)}
                lock = self._send_locks.get(connection)
                if lock:
                    async with lock:
                        await connection.send_json(msg_copy)
                else:
                    await connection.send_json(msg_copy)
            except Exception as exc:
                logger.debug(f"Failed to send to client: {exc}")
                disconnected.add(connection)

        # Remove disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def send_stamped(self, websocket: fastapi.WebSocket, message: dict[str, Any]) -> bool:
        """Send a seq-stamped message to a single client and buffer it.

        Uses the per-connection counter so other clients see no gap.
        Returns True on success, False if the connection was already closed.
        """
        conn_counter = self._per_conn_seq.get(websocket)
        if conn_counter is None:
            return False
        message["seq"] = next(conn_counter)
        message["_buf_seq"] = next(self._buffer_seq)
        self.buffer_message(message)
        try:
            lock = self._send_locks.get(websocket)
            if lock:
                async with lock:
                    await websocket.send_json(message)
            else:
                await websocket.send_json(message)
            return True
        except Exception:
            self.disconnect(websocket)
            return False


# Create connection managers
price_manager = ConnectionManager(name="prices")
trade_manager = ConnectionManager(name="trades")
candle_manager = ConnectionManager(name="candles")
risk_manager = ConnectionManager(name="risk")
equity_manager = ConnectionManager(name="equity")
verdict_manager = ConnectionManager(name="verdict")
signal_manager = ConnectionManager(name="signals")
pipeline_manager = ConnectionManager(name="pipeline")
live_manager = ConnectionManager(name="live")
alerts_manager = ConnectionManager(name="alerts")

# Service instances
_price_feed = PriceFeed()
_trade_ledger = TradeLedger()
_account_manager = AccountManager()
_signal_service = SignalService()

# Event that fires when new prices are available (set by price update loop)
_price_event = asyncio.Event()


async def notify_price_update():
    """Signal all waiting WS loops that new prices are available.

    Call this from wherever prices get ingested (PriceFeed.update_prices,
    Redis subscriber, etc.) to wake the WS push loop immediately.
    """
    _price_event.set()


async def publish_live_update(topic: str, payload: dict[str, object]) -> None:
    """Publish an event to /ws/live subscribers using versioned envelope."""
    await live_manager.broadcast(_ws_event(f"live_event.{topic}", payload))


async def publish_signal_update(signal: Mapping[str, Any]) -> None:
    """Publish a single frozen signal update to /ws/signals subscribers."""
    payload = {str(k): v for k, v in signal.items()}
    await signal_manager.broadcast(_ws_event("signals.update", {"signal": payload}))


async def publish_pipeline_update(
    pair: str,
    pipeline_payload: Mapping[str, Any] | None = None,
) -> bool:
    """Publish a pipeline update to /ws/pipeline subscribers.

    If ``pipeline_payload`` is omitted, this builds from the latest cached L12 verdict.
    Returns ``True`` when an update was broadcast, ``False`` when no payload available.
    """
    pair_upper = pair.upper().strip()
    if not pair_upper:
        return False

    payload_map: dict[str, Any]
    if pipeline_payload is not None:
        payload_map = {str(k): v for k, v in pipeline_payload.items()}
    else:
        verdict = await get_verdict_async(pair_upper)
        if not isinstance(verdict, dict):
            return False
        payload_map = _build_pipeline_data(pair_upper, verdict)

    await pipeline_manager.broadcast(
        _ws_event(
            "pipeline.update",
            {
                "pair": pair_upper,
                "pipeline": payload_map,
            },
        )
    )
    return True


# ---------------------------------------------------------------------------
# Cached risk module singletons (avoid per-push instantiation)
# ---------------------------------------------------------------------------

_cached_risk_manager: object | None = None
_cached_circuit_breaker: object | None = None


def _get_risk_manager():
    """Return a lazily cached RiskManager singleton."""
    global _cached_risk_manager
    if _cached_risk_manager is None:
        try:
            from risk.risk_manager import RiskManager as _RM  # noqa: N814, PLC0415

            _cached_risk_manager = _RM.get_instance()
        except Exception:
            _cached_risk_manager = None
    return _cached_risk_manager


def _get_circuit_breaker():
    """Return a lazily cached CircuitBreaker singleton."""
    global _cached_circuit_breaker
    if _cached_circuit_breaker is None:
        try:
            # CircuitBreaker requires initial_balance; try loading from config
            from config_loader import load_risk  # noqa: PLC0415
            from risk.circuit_breaker import CircuitBreaker as _CB  # noqa: N814, PLC0415

            risk_cfg = load_risk()
            initial_balance = risk_cfg.get("initial_balance", 10_000.0)
            _cached_circuit_breaker = _CB(initial_balance=initial_balance)
        except Exception:
            _cached_circuit_breaker = None
    return _cached_circuit_breaker


# ---------------------------------------------------------------------------
# WS /ws -- General-purpose authenticated signal relay
# ---------------------------------------------------------------------------


@router.websocket("/ws")
async def websocket_general_relay(websocket: fastapi.WebSocket):
    """General-purpose authenticated WebSocket relay.

    Validates JWT, then forwards Redis PubSub ``SIGNAL_EVENTS`` messages
    to the connected client until disconnect.
    """
    await websocket.accept()
    payload = await ws_auth_guard(websocket)
    if not payload:
        return

    from state.pubsub_channels import SIGNAL_EVENTS

    pubsub = None
    try:
        r = await _get_async_redis_client()
        pubsub = r.pubsub()
        await pubsub.subscribe(SIGNAL_EVENTS)
        logger.info("WS /ws connected: user={}", payload.get("sub"))

        while True:
            raw_msg: object = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if raw_msg and isinstance(raw_msg, dict) and raw_msg.get("type") == "message":
                data = raw_msg.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                if isinstance(data, str):
                    await websocket.send_text(data)
            else:
                with contextlib.suppress(Exception):
                    await websocket.send_text(json.dumps({"type": "ping", "ts": time.time()}))
                await asyncio.sleep(1.0)
    except fastapi.WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("WS /ws disconnected: user={}", payload.get("sub"))
    finally:
        if pubsub is not None:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe()
                await pubsub.aclose()


# ---------------------------------------------------------------------------
# WS /ws/prices -- Tick-by-tick price stream
# ---------------------------------------------------------------------------


@router.websocket("/ws/prices")
async def websocket_prices(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for live tick-by-tick price stream.

    Requires ``?token=<jwt_or_api_key>`` query parameter.
    Event-driven: wakes immediately when _price_event is set,
    with a fallback max sleep of TICK_BATCH_INTERVAL to guarantee freshness.

    On connect, replays any buffered messages newer than the client's
    ``since`` query parameter (Unix timestamp), then sends a full snapshot.
    """
    connected = await price_manager.connect(websocket)
    if not connected:
        return
    logger.info("Price WebSocket client connected (event-driven)")

    try:
        # Replay buffered ticks if client supplies ?since=<ts>
        since_ts = websocket.query_params.get("since")
        if since_ts:
            with contextlib.suppress(ValueError, TypeError):
                await price_manager.replay_buffer(websocket, float(since_ts))

        # Send initial snapshot
        prices: dict[str, dict[str, Any]] = (
            await _price_feed.get_latest_prices_async() if hasattr(_price_feed, "get_latest_prices_async") else {}
        )
        snapshot_msg = _ws_event("price.snapshot", {"prices": prices})
        await websocket.send_json(snapshot_msg)

        # Track last known prices to push only diffs
        last_prices: dict[str, dict[str, Any]] = prices.copy()

        while websocket in price_manager.active_connections:
            # Wait for price event OR timeout (whichever comes first)
            try:
                await asyncio.wait_for(
                    _price_event.wait(),
                    timeout=TICK_BATCH_INTERVAL,
                )
                _price_event.clear()
            except TimeoutError:
                pass  # Fallback: check anyway after TICK_BATCH_INTERVAL

            current: dict[str, dict[str, Any]] = (
                await _price_feed.get_latest_prices_async() if hasattr(_price_feed, "get_latest_prices_async") else {}
            )
            changed: dict[str, dict[str, Any]] = {}

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
                tick_msg = _ws_event("price.tick", {"changes": changed})
                if not await price_manager.send_stamped(websocket, tick_msg):
                    break

    except fastapi.WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Price WebSocket error: {exc}")
    finally:
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
        active_trades = await _trade_ledger.get_active_trades_async()
        trades_data = [trade.model_dump() for trade in active_trades]

        await websocket.send_json(_ws_event("trade.snapshot", {"trades": trades_data}))

        # Build initial snapshot
        for trade in active_trades:
            last_trade_snapshot[trade.trade_id] = trade.status.value

        while websocket in trade_manager.active_connections:
            active_trades = await _trade_ledger.get_active_trades_async()
            current_snapshot = {t.trade_id: t.status.value for t in active_trades}

            changed_trades: list[Any] = []
            for trade in active_trades:
                last_status = last_trade_snapshot.get(trade.trade_id)
                if last_status != trade.status.value:
                    changed_trades.append(trade)
                    last_trade_snapshot[trade.trade_id] = trade.status.value

            removed_trade_ids = set(last_trade_snapshot.keys()) - set(current_snapshot.keys())
            for trade_id in removed_trade_ids:
                del last_trade_snapshot[trade_id]

            if changed_trades or removed_trade_ids:
                ok = await trade_manager.send_stamped(
                    websocket,
                    _ws_event(
                        "trade.update",
                        {
                            "changed": [t.model_dump() for t in changed_trades],
                            "removed": list(removed_trade_ids),
                        },
                    ),
                )
                if not ok:
                    break

            # 250ms for near-instant trade event delivery
            await asyncio.sleep(TRADE_CHECK_INTERVAL)

    except fastapi.WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Trade WebSocket error: {exc}")
    finally:
        trade_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# WS /ws/candles -- Real-time candle bar stream
# ---------------------------------------------------------------------------


@router.websocket("/ws/candles")
async def websocket_candles(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for real-time OHLC candle updates.

    Pushes forming bars every 500ms and closed bar events.
    Data sourced from Redis (Dual-Zone SSOT v5 — display only, zero computation).
    Query params: ?token=<jwt>&symbol=<EURUSD> (optional symbol filter)

    Each ``candle.forming`` event includes a ``feed_meta`` field with:
      - ``ingest_status``: "HEALTHY" | "DEGRADED" | "NO_PRODUCER" | "UNKNOWN"
      - ``provider_connected``: bool (Finnhub WS connected)
      - ``symbols``: per-symbol ``{ feed_status, age_seconds }``
    This allows the dashboard to show appropriate status indicators
    when the ingest pipeline is down or data is stale.
    """
    connected = await candle_manager.connect(websocket)
    if not connected:
        return

    # Optional symbol filter
    symbol_filter = websocket.query_params.get("symbol")
    logger.info(f"Candle WebSocket connected (filter={symbol_filter or 'all'})")

    # Feed meta polling: check every 5s (not every 500ms) to avoid Redis overhead
    _FEED_META_INTERVAL = 5.0
    _last_feed_meta_ts: float = 0.0
    _cached_feed_meta: dict[str, object] = {}

    try:
        # Send current bars snapshot with initial feed meta
        snapshot = _candle_agg.get_combined_snapshot(symbol_filter)
        try:
            _cached_feed_meta = await _candle_agg.fetch_feed_meta_async(symbol_filter)
            _last_feed_meta_ts = time.time()
        except Exception:
            pass
        await websocket.send_json(
            _ws_event("candle.snapshot", {"bars": snapshot, "feed_meta": _cached_feed_meta})
        )

        while websocket in candle_manager.active_connections:
            forming = await _candle_agg.fetch_forming_bars_async(symbol_filter)

            # Refresh feed meta periodically (every 5s, not every tick)
            now = time.time()
            if now - _last_feed_meta_ts >= _FEED_META_INTERVAL:
                try:
                    _cached_feed_meta = await _candle_agg.fetch_feed_meta_async(symbol_filter)
                except Exception:
                    pass
                _last_feed_meta_ts = now

            if not await candle_manager.send_stamped(
                websocket,
                _ws_event("candle.forming", {"bars": forming, "feed_meta": _cached_feed_meta}),
            ):
                break
            await asyncio.sleep(CANDLE_UPDATE_INTERVAL)

    except fastapi.WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Candle WebSocket error: {exc}")
    finally:
        candle_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# WS /ws/risk -- Risk state stream
# ---------------------------------------------------------------------------


@router.websocket("/ws/risk")
async def websocket_risk(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for risk state monitoring.

    Pushes drawdown, circuit breaker, and prop firm guard state every 1s.
    Uses cached singleton instances — no per-push instantiation.
    """
    connected = await risk_manager.connect(websocket)
    if not connected:
        return
    logger.info("Risk WebSocket client connected")

    try:
        while websocket in risk_manager.active_connections:
            # Build risk state from cached singletons
            risk_state: dict[str, Any] = {"ts": time.time()}

            rm = _get_risk_manager()
            if rm is not None:
                try:
                    snapshot = rm.get_risk_snapshot()  # type: ignore[union-attr]
                    risk_state["risk_snapshot"] = snapshot
                except Exception:
                    risk_state["risk_snapshot"] = None
            else:
                risk_state["risk_snapshot"] = None

            cb = _get_circuit_breaker()
            if cb is not None:
                try:
                    risk_state["circuit_breaker"] = {
                        "state": cb.state.value if hasattr(cb, "state") else "UNKNOWN",  # type: ignore[union-attr]
                        "is_open": cb.is_open() if hasattr(cb, "is_open") else False,  # type: ignore[union-attr]
                    }
                except Exception:
                    risk_state["circuit_breaker"] = None
            else:
                risk_state["circuit_breaker"] = None

            try:
                drawdown_module = importlib.import_module("risk.drawdown")
                drawdown_cls = getattr(drawdown_module, "DrawdownTracker", None)
                dd_instance: Any = drawdown_cls() if callable(drawdown_cls) else None
                get_status = getattr(dd_instance, "get_status", None) if dd_instance is not None else None
                risk_state["drawdown"] = get_status() if callable(get_status) else None
            except Exception:
                risk_state["drawdown"] = None

            msg = _ws_event("risk.state", risk_state)
            if not await risk_manager.send_stamped(websocket, msg):
                break
            await asyncio.sleep(RISK_STATE_INTERVAL)

    except fastapi.WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Risk WebSocket error: {exc}")
    finally:
        risk_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# WS /ws/equity -- Streaming equity curve with drawdown overlay
# ---------------------------------------------------------------------------

# In-memory equity history buffer (ring buffer, max 1440 points = 24h at 1min)
_EQUITY_HISTORY_MAX = 1440
_equity_history: list[dict[str, object]] = []


def _compute_drawdown(equity: float, peak: float) -> float:
    """Compute drawdown percentage from peak equity."""
    if peak <= 0:
        return 0.0
    return round((peak - equity) / peak * 100.0, 4)


def _available_pairs() -> list[str]:
    """Load enabled symbols for verdict snapshot/stream."""
    symbols: list[str] = []
    with contextlib.suppress(Exception):
        for pair in load_pairs():
            symbol = str(pair.get("symbol", "")).upper().strip()
            if symbol and bool(pair.get("enabled", True)):
                symbols.append(symbol)
    return list(dict.fromkeys(symbols))


def _verdict_signature(data: Mapping[str, Any] | None) -> str:
    """Stable signature used to diff verdict updates."""
    if data is None:
        return ""
    try:
        return json.dumps(data, sort_keys=True, default=str)
    except Exception:
        return str(cast(object, data))


async def _get_verdict_snapshot(pair_filter: str | None = None) -> dict[str, dict[str, Any]]:
    """Read current verdict cache for one pair or all enabled pairs."""
    symbols = [pair_filter.upper()] if pair_filter else _available_pairs()
    snapshot: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        with contextlib.suppress(Exception):
            data = await get_verdict_async(symbol)
            if isinstance(data, dict):
                snapshot[symbol] = data
    return snapshot


async def _detect_changed_verdicts(
    last_signatures: dict[str, str],
    pair_filter: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return only verdict entries that changed since the last scan."""
    current = await _get_verdict_snapshot(pair_filter)
    changed: dict[str, dict[str, Any]] = {}

    for pair, verdict in current.items():
        signature = _verdict_signature(verdict)
        if last_signatures.get(pair) != signature:
            changed[pair] = verdict
            last_signatures[pair] = signature

    current_keys = set(current.keys())
    for pair in list(last_signatures.keys()):
        if pair_filter and pair != pair_filter:
            continue
        if pair not in current_keys:
            del last_signatures[pair]

    return changed


def _signal_signature(item: Mapping[str, Any] | None) -> str:
    if item is None:
        return ""
    try:
        return json.dumps(item, sort_keys=True, default=str)
    except Exception:
        return str(cast(object, item))


def _signal_key(item: Mapping[str, Any]) -> str:
    signal_id = str(item.get("signal_id") or "").strip()
    if signal_id:
        return signal_id
    symbol = str(item.get("symbol") or item.get("pair") or "UNKNOWN").upper()
    timestamp = str(item.get("timestamp") or item.get("created_at") or "")
    return f"{symbol}:{timestamp}"


async def _signal_snapshot_async(symbol_filter: str | None = None) -> dict[str, dict[str, Any]]:
    """Async variant of the signal snapshot — uses batched Redis mget via the
    async Redis client to avoid blocking the event loop.

    This replaces the former sync ``_signal_snapshot()`` in all WS handlers.
    """
    items = (
        await _signal_service.list_by_symbol_async(symbol_filter)
        if symbol_filter
        else await _signal_service.list_all_async()
    )
    snapshot: dict[str, dict[str, Any]] = {}
    for item in items:
        snapshot[_signal_key(item)] = item
    return snapshot


async def _detect_changed_signals_async(
    last_signatures: dict[str, str],
    symbol_filter: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Async variant of _detect_changed_signals."""
    current = await _signal_snapshot_async(symbol_filter)
    changed: dict[str, dict[str, Any]] = {}

    for key, signal in current.items():
        signature = _signal_signature(signal)
        if last_signatures.get(key) != signature:
            changed[key] = signal
            last_signatures[key] = signature

    for key in list(last_signatures.keys()):
        if key not in current:
            del last_signatures[key]

    return changed


async def _pipeline_snapshot(pair_filter: str | None = None) -> dict[str, dict[str, Any]]:
    verdicts = await _get_verdict_snapshot(pair_filter)
    pipelines: dict[str, dict[str, Any]] = {}
    for pair, verdict in verdicts.items():
        with contextlib.suppress(Exception):
            pipelines[pair] = _build_pipeline_data(pair, verdict)
    return pipelines


async def _detect_changed_pipeline(
    last_signatures: dict[str, str],
    pair_filter: str | None = None,
) -> dict[str, dict[str, Any]]:
    current = await _pipeline_snapshot(pair_filter)
    changed: dict[str, dict[str, Any]] = {}

    for pair, payload in current.items():
        signature = _verdict_signature(payload)
        if last_signatures.get(pair) != signature:
            changed[pair] = payload
            last_signatures[pair] = signature

    for pair in list(last_signatures.keys()):
        if pair_filter and pair != pair_filter:
            continue
        if pair not in current:
            del last_signatures[pair]

    return changed


def _read_pubsub_message(pubsub: Any, timeout: float = 1.0) -> Mapping[str, Any] | None:
    """Typed wrapper around Redis pubsub.get_message for pyright-safe narrowing.

    .. deprecated::
        Use :func:`_async_read_pubsub_message` in async WS handlers instead.
        This sync helper is kept only for non-WS contexts that still require it.
    """
    raw: object = pubsub.get_message(
        ignore_subscribe_messages=True,
        timeout=timeout,
    )
    if isinstance(raw, Mapping):
        return cast(Mapping[str, Any], raw)
    return None


async def _async_read_pubsub_message(
    pubsub: _AsyncPubSub,
    timeout: float = 1.0,
) -> Mapping[str, Any] | None:
    """Read one message from an async Redis pubsub without blocking the event loop.

    Returns the message mapping when a data message arrives, ``None`` on timeout
    or non-data messages (subscribe confirmations, etc.).
    """
    raw: object = await pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
    if isinstance(raw, Mapping):
        return cast(Mapping[str, Any], raw)
    return None


async def _make_async_pubsub(channel: str) -> _AsyncPubSub | None:
    """Create an async Redis pubsub instance subscribed to *channel*.

    Returns ``None`` on any error so callers can fall back to polling gracefully.
    Uses the shared async connection pool from :mod:`infrastructure.redis_client`
    to avoid per-connection pool exhaustion that occurs with the sync singleton.
    """
    try:
        client = await _get_async_redis_client()
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub
    except Exception as exc:
        logger.warning("[WS] Failed to create async pubsub for channel {}: {}", channel, exc)
        return None


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
        await websocket.send_json(
            _ws_event(
                "equity.snapshot",
                {
                    "history": list(_equity_history),
                },
            )
        )

        while websocket in equity_manager.active_connections:
            # Fetch current account state
            equity_point: dict[str, object] = {"ts": time.time()}

            try:
                from accounts.account_manager import AccountManager  # noqa: PLC0415

                am = AccountManager()
                accounts = await am.list_accounts_async()

                if account_filter:
                    account = await am.get_account_async(account_filter)
                    accounts = [account] if account else []

                if accounts:
                    # Use first/filtered account
                    acct = accounts[0]
                    equity = float(acct.equity)
                    balance = float(acct.balance)
                    floating_pnl = round(equity - balance, 2)

                    # Track peak for drawdown calc
                    if equity > peak_equity:
                        peak_equity = equity

                    drawdown_pct = _compute_drawdown(equity, peak_equity)

                    equity_point.update(
                        {
                            "equity": equity,
                            "balance": balance,
                            "floating_pnl": floating_pnl,
                            "peak_equity": peak_equity,
                            "drawdown_pct": drawdown_pct,
                        }
                    )
                else:
                    equity_point.update(
                        {
                            "equity": 0.0,
                            "balance": 0.0,
                            "floating_pnl": 0.0,
                            "peak_equity": 0.0,
                            "drawdown_pct": 0.0,
                        }
                    )

            except Exception as exc:
                logger.debug(f"Equity fetch failed: {exc}")
                equity_point.update(
                    {
                        "equity": 0.0,
                        "balance": 0.0,
                        "floating_pnl": 0.0,
                        "peak_equity": 0.0,
                        "drawdown_pct": 0.0,
                        "error": str(exc),
                    }
                )

            raw_equity = equity_point.get("equity", 0.0)
            current_equity = float(raw_equity) if isinstance(raw_equity, int | float) else 0.0

            # Only append to history if equity changed (avoid flat duplicates)
            if last_equity is None or current_equity != last_equity:
                _equity_history.append(equity_point)
                if len(_equity_history) > _EQUITY_HISTORY_MAX:
                    _equity_history.pop(0)
                last_equity = current_equity

            # Push update to client
            if not await equity_manager.send_stamped(websocket, _ws_event("equity.update", equity_point)):
                break

            await asyncio.sleep(EQUITY_PUSH_INTERVAL)

    except fastapi.WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Equity WebSocket error: {exc}")
    finally:
        equity_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# WS /ws/verdict -- Real-time L12 verdict stream
# ---------------------------------------------------------------------------


@router.websocket("/ws/verdict")
async def websocket_verdict(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for L12 verdict updates.

    Flow:
    - On connect, send verdict.snapshot (all enabled pairs or one pair filter)
    - Listen to Redis pub/sub VERDICT_READY events for near-instant push
    - Run 500ms fallback diff scan to tolerate missed events / legacy writers

    Query params:
      ?token=<jwt_or_api_key>
      ?pair=<EURUSD>  (optional symbol filter)
    """
    connected = await verdict_manager.connect(websocket)
    if not connected:
        return

    pair_filter = str(websocket.query_params.get("pair") or "").upper().strip() or None
    logger.info(f"Verdict WebSocket client connected (pair={pair_filter or 'all'})")

    signatures: dict[str, str] = {}
    pubsub: _AsyncPubSub | None = None

    try:
        snapshot = await _get_verdict_snapshot(pair_filter)
        for pair, verdict in snapshot.items():
            signatures[pair] = _verdict_signature(verdict)

        await websocket.send_json(
            _ws_event(
                "verdict.snapshot",
                {
                    "pair": pair_filter,
                    "verdicts": snapshot,
                },
            )
        )

        pubsub = await _make_async_pubsub(VERDICT_READY_CHANNEL)

        last_scan_ts = 0.0

        while websocket in verdict_manager.active_connections:
            pushed = False

            if pubsub is not None:
                message_map = await _async_read_pubsub_message(pubsub, 1.0)

                if message_map is not None and message_map.get("type") == "message":
                    raw: Any = message_map.get("data")
                    event: dict[str, Any] = {}
                    with contextlib.suppress(Exception):
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            event = cast(dict[str, Any], parsed)

                    pair_raw: Any = event.get("pair", "")
                    pair = str(pair_raw).upper().strip()
                    if pair and (pair_filter is None or pair_filter == pair):
                        verdict_raw = await get_verdict_async(pair)
                        if isinstance(verdict_raw, Mapping):
                            verdict_map = cast(Mapping[str, Any], verdict_raw)
                            verdict: dict[str, Any] = {k: v for k, v in verdict_map.items()}
                            signature = _verdict_signature(verdict)
                            signatures[pair] = signature
                            if not await verdict_manager.send_stamped(
                                websocket,
                                _ws_event(
                                    "verdict.update",
                                    {
                                        "pair": pair,
                                        "verdict": verdict,
                                    },
                                ),
                            ):
                                break
                            pushed = True

            now_ts = time.time()
            if (not pushed) and (now_ts - last_scan_ts >= VERDICT_FALLBACK_INTERVAL):
                changed = await _detect_changed_verdicts(signatures, pair_filter)
                for pair, verdict in changed.items():
                    if not await verdict_manager.send_stamped(
                        websocket,
                        _ws_event(
                            "verdict.update",
                            {
                                "pair": pair,
                                "verdict": verdict,
                            },
                        ),
                    ):
                        break
                last_scan_ts = now_ts

            await asyncio.sleep(0.05)

    except fastapi.WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Verdict WebSocket error: {exc}")
    finally:
        verdict_manager.disconnect(websocket)
        if pubsub is not None:
            try:
                await pubsub.aclose()
            except Exception as exc:
                logger.warning("[WS/verdict] pubsub cleanup error: {}", exc)


# ---------------------------------------------------------------------------
# WS /ws/signals -- Real-time frozen SignalContract stream
# ---------------------------------------------------------------------------


@router.websocket("/ws/signals")
async def websocket_signals(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for frozen signal updates.

    Flow:
    - On connect, send signals.snapshot (all or symbol-filtered)
    - Listen to Redis pub/sub SIGNAL_READY events
    - Run 500ms fallback diff scan to cover missed events

    Query params:
      ?token=<jwt_or_api_key>
      ?symbol=<EURUSD>  (optional symbol filter)
    """
    connected = await signal_manager.connect(websocket)
    if not connected:
        return

    symbol_filter = str(websocket.query_params.get("symbol") or "").upper().strip() or None
    logger.info(f"Signals WebSocket client connected (symbol={symbol_filter or 'all'})")

    signatures: dict[str, str] = {}
    pubsub: _AsyncPubSub | None = None

    try:
        snapshot = await _signal_snapshot_async(symbol_filter)
        for key, signal in snapshot.items():
            signatures[key] = _signal_signature(signal)

        await websocket.send_json(
            _ws_event(
                "signals.snapshot",
                {
                    "symbol": symbol_filter,
                    "signals": list(snapshot.values()),
                },
            )
        )

        pubsub = await _make_async_pubsub(SIGNAL_READY_CHANNEL)

        last_scan_ts = 0.0

        while websocket in signal_manager.active_connections:
            pushed = False

            if pubsub is not None:
                message_map = await _async_read_pubsub_message(pubsub, 1.0)

                if message_map is not None and message_map.get("type") == "message":
                    latest = await _signal_snapshot_async(symbol_filter)
                    for key, signal in latest.items():
                        signatures[key] = _signal_signature(signal)
                        if not await signal_manager.send_stamped(
                            websocket,
                            _ws_event(
                                "signals.update",
                                {
                                    "signal": signal,
                                },
                            ),
                        ):
                            break
                        pushed = True

            now_ts = time.time()
            if (not pushed) and (now_ts - last_scan_ts >= SIGNAL_FALLBACK_INTERVAL):
                changed = await _detect_changed_signals_async(signatures, symbol_filter)
                for signal in changed.values():
                    if not await signal_manager.send_stamped(
                        websocket,
                        _ws_event(
                            "signals.update",
                            {
                                "signal": signal,
                            },
                        ),
                    ):
                        break
                last_scan_ts = now_ts

            await asyncio.sleep(0.05)

    except fastapi.WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Signals WebSocket error: {exc}")
    finally:
        signal_manager.disconnect(websocket)
        if pubsub is not None:
            try:
                await pubsub.aclose()
            except Exception as exc:
                logger.warning("[WS/signals] pubsub cleanup error: {}", exc)


# ---------------------------------------------------------------------------
# WS /ws/pipeline -- Real-time pipeline panel stream
# ---------------------------------------------------------------------------


@router.websocket("/ws/pipeline")
async def websocket_pipeline(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for pipeline panel updates.

    Flow:
    - On connect, send pipeline.snapshot from current L12 cache
    - Listen to VERDICT_READY events (pipeline completion trigger)
    - Run 500ms fallback diff scan for missed events

    Query params:
      ?token=<jwt_or_api_key>
      ?pair=<EURUSD>  (optional pair filter)
    """
    connected = await pipeline_manager.connect(websocket)
    if not connected:
        return

    pair_filter = str(websocket.query_params.get("pair") or "").upper().strip() or None
    logger.info(f"Pipeline WebSocket client connected (pair={pair_filter or 'all'})")

    signatures: dict[str, str] = {}
    pubsub: _AsyncPubSub | None = None

    try:
        snapshot = await _pipeline_snapshot(pair_filter)
        for pair, payload in snapshot.items():
            signatures[pair] = _verdict_signature(payload)

        await websocket.send_json(
            _ws_event(
                "pipeline.snapshot",
                {
                    "pair": pair_filter,
                    "pipelines": snapshot,
                },
            )
        )

        pubsub = await _make_async_pubsub(VERDICT_READY_CHANNEL)

        last_scan_ts = 0.0

        while websocket in pipeline_manager.active_connections:
            pushed = False

            if pubsub is not None:
                message_map = await _async_read_pubsub_message(pubsub, 1.0)

                if message_map is not None and message_map.get("type") == "message":
                    latest = await _pipeline_snapshot(pair_filter)
                    for pair, payload in latest.items():
                        signatures[pair] = _verdict_signature(payload)
                        if not await pipeline_manager.send_stamped(
                            websocket,
                            _ws_event(
                                "pipeline.update",
                                {
                                    "pair": pair,
                                    "pipeline": payload,
                                },
                            ),
                        ):
                            break
                        pushed = True

            now_ts = time.time()
            if (not pushed) and (now_ts - last_scan_ts >= PIPELINE_FALLBACK_INTERVAL):
                changed = await _detect_changed_pipeline(signatures, pair_filter)
                for pair, payload in changed.items():
                    if not await pipeline_manager.send_stamped(
                        websocket,
                        _ws_event(
                            "pipeline.update",
                            {
                                "pair": pair,
                                "pipeline": payload,
                            },
                        ),
                    ):
                        break
                last_scan_ts = now_ts

            await asyncio.sleep(0.05)

    except fastapi.WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Pipeline WebSocket error: {exc}")
    finally:
        pipeline_manager.disconnect(websocket)
        if pubsub is not None:
            try:
                await pubsub.aclose()
            except Exception as exc:
                logger.warning("[WS/pipeline] pubsub cleanup error: {}", exc)


# ---------------------------------------------------------------------------
# WS /ws/live -- Unified live feed (signals + accounts + trades)
# ---------------------------------------------------------------------------


@router.websocket("/ws/live")
async def websocket_live_feed(websocket: fastapi.WebSocket):
    """Unified live feed for dashboard widgets and risk preview modal state."""
    connected = await live_manager.connect(websocket)
    if not connected:
        return

    try:
        await websocket.send_json(
            _ws_event(
                "live.snapshot",
                {
                    "signals": await _signal_service.list_all_async(),
                    "accounts": [a.model_dump() for a in await _account_manager.list_accounts_async()],
                    "trades": [t.model_dump() for t in await _trade_ledger.get_active_trades_async()],
                },
            )
        )

        while websocket in live_manager.active_connections:
            # Keepalive periodic state update for clients that miss individual events.
            # Includes engine health so dashboard can distinguish "WS alive,
            # engine stalled" from "WS dead".
            engine_producing = False
            with contextlib.suppress(Exception):
                _pairs = load_pairs()
                _sample_symbol = str(_pairs[0].get("symbol", "")) if _pairs else ""
                if _sample_symbol:
                    _v = await get_verdict_async(_sample_symbol)
                    if _v and "_cached_at" in _v:
                        engine_producing = (time.time() - float(_v["_cached_at"])) < 120

            ok = await live_manager.send_stamped(
                websocket,
                _ws_event(
                    "live.heartbeat_state",
                    {
                        "signal_count": len(await _signal_service.list_all_async()),
                        "account_count": len(await _account_manager.list_accounts_async()),
                        "active_trade_count": len(await _trade_ledger.get_active_trades_async()),
                        "server_ts": time.time(),
                        "engine_status": "ok" if engine_producing else "stalled",
                    },
                ),
            )
            if not ok:
                break
            await asyncio.sleep(1.0)

    except fastapi.WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Live WebSocket error: {exc}")
    finally:
        live_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# WS /ws/alerts -- Event-driven alert stream (risk events, trade events)
# ---------------------------------------------------------------------------


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for real-time alert events.

    Subscribes to RISK_EVENTS pub/sub and pushes alert payloads to
    connected dashboard clients.  Event-driven only — no polling fallback.

    Query params:
      ?token=<jwt_or_api_key>
    """
    connected = await alerts_manager.connect(websocket)
    if not connected:
        return

    logger.info("Alerts WebSocket client connected")
    pubsub: _AsyncPubSub | None = None

    try:
        pubsub = await _make_async_pubsub(RISK_EVENTS)

        while websocket in alerts_manager.active_connections:
            pushed = False

            if pubsub is not None:
                message_map = await _async_read_pubsub_message(pubsub, 1.0)

                if message_map is not None and message_map.get("type") == "message":
                    raw: Any = message_map.get("data")
                    event: dict[str, Any] = {}
                    with contextlib.suppress(Exception):
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            event = cast(dict[str, Any], parsed)

                    if event:
                        if not await alerts_manager.send_stamped(
                            websocket,
                            _ws_event("alert.event", event),
                        ):
                            break
                        pushed = True

            if not pushed:
                await asyncio.sleep(0.5)

    except fastapi.WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Alerts WebSocket error: {exc}")
    finally:
        alerts_manager.disconnect(websocket)
        if pubsub is not None:
            try:
                await pubsub.aclose()
            except Exception as exc:
                logger.warning("[WS/alerts] pubsub cleanup error: {}", exc)


# ---------------------------------------------------------------------------
# WS /ws/trq -- TRQ pre-move alert stream (Zone A micro-wave)
# ---------------------------------------------------------------------------

trq_manager = ConnectionManager(name="trq")


@router.websocket("/ws/trq")
async def websocket_trq(websocket: fastapi.WebSocket):
    """
    WebSocket endpoint for TRQ pre-move alerts (Zone A micro-wave analysis).

    Pushes TRQ snapshots every 2s.  Data sourced from Redis — display only.
    Query params: ?token=<jwt>&symbol=<EURUSD> (optional symbol filter)
    """
    connected = await trq_manager.connect(websocket)
    if not connected:
        return

    symbol_filter = websocket.query_params.get("symbol")
    logger.info(f"TRQ WebSocket connected (filter={symbol_filter or 'all'})")

    try:
        # Initial snapshot
        snapshot = _candle_agg.get_trq_snapshot(symbol_filter)
        await websocket.send_json(_ws_event("trq.snapshot", {"data": snapshot}))

        while websocket in trq_manager.active_connections:
            snapshot = _candle_agg.get_trq_snapshot(symbol_filter)
            if not await trq_manager.send_stamped(websocket, _ws_event("trq.update", {"data": snapshot})):
                break
            await asyncio.sleep(2.0)

    except fastapi.WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"TRQ WebSocket error: {exc}")
    finally:
        trq_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# REST /api/v1/trq/{symbol}/r3d -- R3D history (Zone A)
# ---------------------------------------------------------------------------


@router.get("/api/v1/trq/{symbol}/r3d")
async def get_trq_r3d_history(symbol: str) -> dict[str, Any]:
    """Return TRQ R3D history list for a symbol.

    Reads up to 100 most-recent R3D values from Redis.
    Returns empty list when no data is available (graceful degradation).

    Authentication: requires valid JWT or API key via Authorization header.
    """
    sym_upper = symbol.upper()
    try:
        from core.redis_keys import trq_r3d_history as _trq_r3d_history
        from infrastructure.redis_client import get_client

        redis = await get_client()
        raw_entries: list[Any] = await redis.lrange(_trq_r3d_history(sym_upper), -100, -1)  # pyright: ignore[reportGeneralTypeIssues]
    except Exception as exc:
        logger.warning("[TRQ R3D] Redis read failed {}: {}", sym_upper, exc)
        return {"symbol": sym_upper, "r3d_history": [], "count": 0}

    import orjson as _orjson  # noqa: PLC0415

    history: list[dict[str, Any]] = []
    for entry in raw_entries:
        try:
            data = _orjson.loads(entry) if isinstance(entry, (bytes, str)) else entry
            history.append(data)
        except Exception:
            pass

    return {"symbol": sym_upper, "r3d_history": history, "count": len(history)}
