"""Lightweight async health probe server for container orchestration.

Exposes ``/healthz`` (liveness), ``/health`` (liveness alias), ``/readyz``
(readiness) and ``/status`` endpoints on a configurable port.  Zero external
dependencies — uses only ``asyncio``.

Usage::

    probe = HealthProbe(port=8081, service_name="engine")
    probe.set_readiness_check(lambda: my_component.is_ready())
    asyncio.create_task(probe.start())

Docker Compose healthcheck example::

    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8081/healthz', timeout=5)"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
import time
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable

_DEFAULT_LIVENESS_PORT = 8081


class HealthProbe:
    """Minimal async HTTP health server for Docker / Kubernetes probes.

    Parameters
    ----------
    port:
        TCP port to listen on (default 8081).
    service_name:
        Human-readable service identifier included in responses.
    readiness_check:
        Optional callable returning ``True`` when the service is ready to
        serve traffic.  Called on every ``/readyz`` request; keep it fast.
    """

    def __init__(
        self,
        port: int = _DEFAULT_LIVENESS_PORT,
        service_name: str = "unknown",
        readiness_check: Callable[[], bool] | None = None,
    ) -> None:
        self._port = port
        self._service_name = service_name
        self._readiness_check = readiness_check or (lambda: True)
        self._started_at = time.monotonic()
        self._server: asyncio.Server | None = None
        self._alive = True
        self._details: dict[str, str] = {}

    # ── public setters ──────────────────────────────────────────────

    def set_alive(self, alive: bool) -> None:
        """Mark liveness state (``False`` → ``/healthz`` returns 503)."""
        self._alive = alive

    def set_readiness_check(self, check: Callable[[], bool]) -> None:
        self._readiness_check = check

    def set_detail(self, key: str, value: str) -> None:
        """Attach extra key-value metadata included in probe responses."""
        self._details[key] = value

    # ── detail classification ──────────────────────────────────────

    #: Keys considered safe for unauthenticated probes (status-only, no
    #: internal errors or state fragments).
    _SAFE_DETAIL_KEYS: frozenset[str] = frozenset(
        {
            "startup_stage",
            "warmup",
            "warmup_retry",
        }
    )

    # ── HTTP handling ───────────────────────────────────────────────

    @staticmethod
    def _parse_request(raw: bytes) -> tuple[str, dict[str, str]]:
        """Extract path and headers from a raw HTTP request."""
        text = raw.decode("utf-8", errors="replace")
        lines = text.split("\r\n")
        request_line = lines[0] if lines else ""
        parts = request_line.split(" ")
        raw_path = parts[1] if len(parts) > 1 else "/"
        parsed = urlparse(raw_path)
        path = parsed.path

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line:
                break
            if ": " in line:
                k, _, v = line.partition(": ")
                headers[k.lower()] = v.strip()

        # Attach query params for token extraction
        qs = parse_qs(parsed.query)
        token_vals = qs.get("token", [])
        if token_vals:
            headers["_query_token"] = token_vals[0]

        return path, headers

    def _is_authenticated(self, headers: dict[str, str]) -> bool:
        """Check if the request carries a valid HEALTH_PROBE_TOKEN."""
        expected = os.environ.get("HEALTH_PROBE_TOKEN", "").strip()
        if not expected:
            # No token configured → deny /status (fail-closed)
            return False

        # Check Authorization: Bearer <token>
        auth_header = headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            presented = auth_header[7:].strip()
            if presented and hmac.compare_digest(presented, expected):
                return True

        # Check ?token=<value> query param
        query_token = headers.get("_query_token", "")
        return bool(query_token and hmac.compare_digest(query_token, expected))

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            path, headers = self._parse_request(data)

            if path in ("/healthz", "/health"):
                response = self._liveness_response()
            elif path == "/readyz":
                response = self._readiness_response()
            elif path == "/status":
                response = self._status_response() if self._is_authenticated(headers) else self._unauthorized_response()
            else:
                response = self._not_found_response()

            writer.write(response.encode())
            await writer.drain()
        except Exception:
            # probe failures must never crash the service
            return
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def _safe_details(self) -> dict[str, str]:
        """Return only non-sensitive detail keys for unauthenticated probes."""
        return {k: v for k, v in self._details.items() if k in self._SAFE_DETAIL_KEYS}

    def _liveness_response(self) -> str:
        uptime = int(time.monotonic() - self._started_at)
        body: dict[str, object] = {
            "status": "alive" if self._alive else "dead",
            "service": self._service_name,
            "uptime_sec": uptime,
        }
        status_code = 200 if self._alive else 503
        status_text = "OK" if self._alive else "Service Unavailable"
        return self._http_response(status_code, status_text, body)

    def _readiness_response(self) -> str:
        try:
            ready = self._readiness_check()
        except Exception:
            ready = False
        body: dict[str, object] = {
            "status": "ready" if ready else "not_ready",
            "service": self._service_name,
        }
        status_code = 200 if ready else 503
        status_text = "OK" if ready else "Service Unavailable"
        return self._http_response(status_code, status_text, body)

    def _status_response(self) -> str:
        """Combined liveness + readiness + all detail metadata (authenticated only)."""
        try:
            ready = self._readiness_check()
        except Exception:
            ready = False
        uptime = int(time.monotonic() - self._started_at)
        body: dict[str, object] = {
            "alive": self._alive,
            "ready": ready,
            "service": self._service_name,
            "uptime_sec": uptime,
            **self._details,
        }
        ok = self._alive and ready
        code = 200 if ok else 503
        text = "OK" if ok else "Service Unavailable"
        return self._http_response(code, text, body)

    @staticmethod
    def _unauthorized_response() -> str:
        body = {
            "error": "unauthorized",
            "hint": "Set HEALTH_PROBE_TOKEN and pass via Authorization header or ?token= query param",
        }
        return HealthProbe._http_response(401, "Unauthorized", body)

    @staticmethod
    def _not_found_response() -> str:
        body = {"error": "not_found", "hint": "Use /health, /healthz, /readyz, or /status"}
        return HealthProbe._http_response(404, "Not Found", body)

    @staticmethod
    def _http_response(code: int, status: str, body: dict) -> str:
        payload = json.dumps(body)
        return (
            f"HTTP/1.1 {code} {status}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{payload}"
        )

    # ── lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the probe server (blocks forever via ``serve_forever``)."""
        self._server = await asyncio.start_server(self._handle, "0.0.0.0", self._port)
        logger.info(
            f"Health probe listening on :{self._port} "
            f"(service={self._service_name}, endpoints=/healthz /readyz /status)"
        )
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Gracefully stop the probe server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info(f"Health probe stopped (service={self._service_name})")
