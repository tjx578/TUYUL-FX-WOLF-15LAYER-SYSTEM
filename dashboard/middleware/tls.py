"""
TLS enforcement middleware.

Zone: dashboard (infrastructure security).

Ensures all HTTP traffic is redirected to HTTPS. Handles both
direct TLS termination and reverse proxy (X-Forwarded-Proto) scenarios.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Set to "1" or "true" to disable (e.g., local dev only)
_TLS_DISABLED = os.environ.get("DISABLE_TLS_REDIRECT", "").lower() in ("1", "true")
# Trust X-Forwarded-Proto from reverse proxy
_TRUST_PROXY = os.environ.get("TRUST_PROXY_HEADERS", "").lower() in ("1", "true")


class TLSRedirectMiddleware:
    """
    ASGI middleware that enforces HTTPS.

    Behavior:
    - If request is HTTP (not HTTPS), returns 301 redirect to HTTPS equivalent.
    - Respects X-Forwarded-Proto when TRUST_PROXY_HEADERS is set.
    - Health check endpoints (/health, /readyz) are exempt (for load balancers).
    - Sends HSTS header on HTTPS responses.

    Usage with FastAPI:
        app.add_middleware(TLSRedirectMiddleware)
    """

    EXEMPT_PATHS = {"/health", "/readyz", "/livez"}
    HSTS_MAX_AGE = 31536000  # 1 year

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if _TLS_DISABLED:
            await self.app(scope, receive, send)
            return

        # Determine if connection is secure
        is_secure = scope.get("scheme") in ("https", "wss")

        if not is_secure and _TRUST_PROXY:
            # Check X-Forwarded-Proto header
            headers = dict(scope.get("headers", []))
            forwarded_proto = headers.get(b"x-forwarded-proto", b"").decode()
            is_secure = forwarded_proto == "https"

        # Exempt health checks
        path = scope.get("path", "")
        if path in self.EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        if not is_secure:
            if scope["type"] == "websocket":
                # Can't redirect WebSocket — reject
                logger.warning("SECURITY: Rejected insecure WebSocket connection to %s", path)
                await send({
                    "type": "websocket.close",
                    "code": 1008,  # Policy Violation
                })
                return

            # HTTP → HTTPS redirect
            host = ""
            for key, value in scope.get("headers", []):
                if key == b"host":
                    host = value.decode()
                    break

            query_string = scope.get("query_string", b"")
            redirect_url = f"https://{host}{path}"
            if query_string:
                redirect_url += f"?{query_string.decode()}"

            logger.info("TLS redirect: %s → %s", path, redirect_url)

            await send({
                "type": "http.response.start",
                "status": 301,
                "headers": [
                    [b"location", redirect_url.encode()],
                    [b"strict-transport-security",
                     f"max-age={self.HSTS_MAX_AGE}; includeSubDomains".encode()],
                    [b"content-length", b"0"],
                ],
            })
            await send({
                "type": "http.response.body",
                "body": b"",
            })
            return

        # Connection is secure — add HSTS header
        async def send_with_hsts(message: dict) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([
                    b"strict-transport-security",
                    f"max-age={self.HSTS_MAX_AGE}; includeSubDomains".encode(),
                ])
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_hsts)
