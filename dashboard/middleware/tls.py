"""
dashboard/middleware/tls.py — TLS Redirect Middleware (ASGI)

Redirects plain HTTP requests to HTTPS with 301.
Exempt paths: /health (liveness probes must work over HTTP).

Set env DISABLE_TLS_REDIRECT=1 to bypass (local dev).
"""

from __future__ import annotations

import os
from typing import Any

_Scope = dict[str, Any]
_Receive = Any
_Send = Any

_EXEMPT_PATHS = frozenset({"/health", "/healthz", "/ready"})


class TLSRedirectMiddleware:
    """ASGI middleware that issues 301 redirects from HTTP to HTTPS."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        if os.environ.get("DISABLE_TLS_REDIRECT") == "1":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "/")
        if path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        scheme: str = scope.get("scheme", "https")
        if scheme == "https":
            await self.app(scope, receive, send)
            return

        # Build redirect URL
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"localhost").decode("utf-8", errors="replace")
        qs = scope.get("query_string", b"")
        if isinstance(qs, bytes):
            qs = qs.decode("utf-8", errors="replace")
        location = f"https://{host}{path}"
        if qs:
            location += f"?{qs}"

        await send(
            {
                "type": "http.response.start",
                "status": 301,
                "headers": [
                    (b"location", location.encode("utf-8")),
                    (b"content-length", b"0"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})
