"""Shared httpx.AsyncClient for BFF → core-api communication.

Uses a module-level singleton with connection pooling.  The client
is created lazily on first use and closed via the lifespan hook.

Rules (from dashboard-hybrid-topology.md):
- Forward Authorization header unchanged.
- Forward x-request-id unchanged — do NOT generate a new one.
- Do not introduce new auth surfaces.
"""

from __future__ import annotations

import os

import httpx

_client: httpx.AsyncClient | None = None


def _core_api_base() -> str:
    url = os.getenv("INTERNAL_API_URL", "http://localhost:8000")
    return url.rstrip("/")


def get_client() -> httpx.AsyncClient:
    """Return the shared async HTTP client (lazy init)."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=_core_api_base(),
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )
    return _client


async def close_client() -> None:
    """Gracefully close the shared client (call from lifespan shutdown)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
