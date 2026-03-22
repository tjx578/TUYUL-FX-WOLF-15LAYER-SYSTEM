"""
TUYUL FX Wolf-15 — Ingest + WS Load Test (Locust)

Scenarios
---------
WsBehavior      : sustain N concurrent WebSocket clients, measure latency & drops
TickIngest      : flood the REST tick-ingest endpoint (200 ticks/sec equivalent)
ReconnectStorm  : rapid WS connect → close cycles

Run
---
  pip install locust websocket-client
  locust -f tests/load/locust_ingest.py \
    --host http://localhost:8000 \
    --users 200 --spawn-rate 20 \
    --run-time 60s --headless \
    -e TOKEN=<jwt>

    or open the Locust UI at http://localhost:8089

Metrics watched
---------------
  - WS latency (measured via echo / timestamp payload)
  - Dropped WS connections (tracked in _ws_drops counter)
  - Tick HTTP p95 latency
  - Tick rejection rate (HTTP 429)
"""

from __future__ import annotations

import importlib
import json
import os
import random
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

try:
    locust = importlib.import_module("locust")
except ModuleNotFoundError as exc:
    raise RuntimeError("Missing dependency 'locust'. Install it with: pip install locust") from exc

import websocket  # type: ignore[import-not-found]

# ── Config ────────────────────────────────────────────────────────────────────

TOKEN: str = os.environ.get("TOKEN", "")
WS_BASE_URL: str = os.environ.get(
    "WS_BASE_URL",
    os.environ.get("HOST", "ws://localhost:8000").replace("http", "ws"),
)
WS_BASE: str = WS_BASE_URL.rstrip("/") + "/ws"

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCHF"]

# Thread-safe global counters exposed to Locust
_lock = threading.Lock()
_ws_drops: int = 0
_ws_messages: int = 0
_ws_latency_total_ms: float = 0.0


def _fire_request_event(**kwargs: Any) -> None:
    request_event = cast(Any, getattr(locust.events, "request", None))
    fire = cast(Callable[..., None] | None, getattr(request_event, "fire", None))
    if fire is not None:
        fire(**kwargs)


# ── Tick ingest user ──────────────────────────────────────────────────────────


class TickIngestUser(locust.HttpUser):
    """
    Simulates the REST tick-ingest path.
    Target: 200 ticks/sec with 50–100 concurrent VUs.
    """

    def wait_time(self) -> float:
        return random.uniform(0.001, 0.01)  # ~100–1000 req/s per user

    def on_start(self) -> None:
        self._auth_headers: dict[str, str] = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

    @locust.task(10)
    def ingest_tick(self) -> None:
        pair = random.choice(PAIRS)
        price = round(1.0 + random.random() * 0.5, 5)
        payload = {
            "symbol": pair,
            "bid": price,
            "ask": round(price + 0.0002, 5),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        with self.client.post(
            "/api/v1/ingest/tick",
            json=payload,
            headers=self._auth_headers,
            catch_response=True,
            name="POST /api/v1/ingest/tick",
        ) as resp:
            if resp.status_code == 429:
                resp.failure("Rate limited (429)")
            elif not resp.ok:
                resp.failure(f"Unexpected status {resp.status_code}")
            else:
                resp.success()

    @locust.task(1)
    def health_check(self) -> None:
        self.client.get("/health", name="GET /health")


# ── WebSocket user ────────────────────────────────────────────────────────────


def _ws_url(path: str) -> str:
    base = WS_BASE.rstrip("/")
    url = f"{base}{path}"
    return f"{url}?token={TOKEN}" if TOKEN else url


class WsBehavior(locust.HttpUser):
    """
    Sustains a single WebSocket connection per virtual user for the full test
    duration.  Tracks message latency and connection drops.

    Note: Locust's native WS support is minimal; we use websocket-client in a
    background thread so the Locust event loop isn't blocked.
    """

    def wait_time(self) -> float:
        return random.uniform(55, 60)  # each VU re-opens after ~60 s if closed

    def on_start(self) -> None:
        self._connected = False
        self._thread: threading.Thread | None = None
        self._connect()

    def on_stop(self) -> None:
        pass  # ws.close() is called inside the thread naturally

    def _connect(self) -> None:
        url = _ws_url("/prices")
        self._thread = threading.Thread(target=self._run_ws, args=(url,), daemon=True)
        self._thread.start()

    def _run_ws(self, url: str) -> None:
        global _ws_drops, _ws_messages, _ws_latency_total_ms

        ws_app_ctor_obj = getattr(websocket, "WebSocketApp", None)
        if ws_app_ctor_obj is None:
            raise RuntimeError("Missing dependency 'websocket-client'. Install it with: pip install websocket-client")
        ws_app_ctor = cast(Callable[..., Any], ws_app_ctor_obj)

        def on_open(ws_app: Any) -> None:
            ws_app.send(json.dumps({"type": "subscribe", "channel": "prices"}))
            self._connected = True

        def on_message(_: Any, msg: str) -> None:
            global _ws_messages, _ws_latency_total_ms
            now_ms = time.time() * 1000
            try:
                data = json.loads(msg)
                ts_ms = data.get("timestamp_ms", now_ms)
                latency = now_ms - ts_ms
                with _lock:
                    _ws_messages += 1
                    _ws_latency_total_ms += latency
                _fire_request_event(
                    request_type="WS",
                    name="ws/prices frame",
                    response_time=latency,
                    response_length=len(msg),
                )
            except json.JSONDecodeError:
                pass

        def on_error(ws_app: Any, err: Exception) -> None:
            global _ws_drops
            self._connected = False
            with _lock:
                _ws_drops += 1
            _fire_request_event(
                request_type="WS",
                name="ws/prices error",
                response_time=0,
                response_length=0,
                exception=err,
            )

        def on_close(*_) -> None:
            self._connected = False

        app = ws_app_ctor(
            url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        app.run_forever(ping_interval=20, ping_timeout=10)

    @locust.task
    def keep_alive(self) -> None:
        # No polling — the background thread handles incoming frames.
        pass


# ── Reconnect storm user ──────────────────────────────────────────────────────


class ReconnectStormUser(locust.HttpUser):
    """
    Rapidly connects then immediately closes the WS.
    Target: 100 reconnects/sec.  Validates server doesn't accumulate zombies.
    """

    def wait_time(self) -> float:
        return random.uniform(0.005, 0.015)  # ≈ 67–200 req/s per VU

    @locust.task
    def reconnect(self) -> None:
        url = _ws_url("/prices")
        ok = False
        start_ms = time.time() * 1000

        ws_create_connection_obj = getattr(websocket, "create_connection", None)
        if ws_create_connection_obj is None:
            raise RuntimeError("Missing dependency 'websocket-client'. Install it with: pip install websocket-client")
        ws_create_connection = cast(
            Callable[..., Any],
            ws_create_connection_obj,
        )

        try:
            ws_app = ws_create_connection(url, timeout=3)
            ok = ws_app.connected
            ws_app.close()
        except Exception:
            ok = False

        elapsed = time.time() * 1000 - start_ms
        _fire_request_event(
            request_type="WS_RECONNECT",
            name="ws reconnect cycle",
            response_time=elapsed,
            response_length=0,
            exception=None if ok else ConnectionError("reconnect failed"),
        )
