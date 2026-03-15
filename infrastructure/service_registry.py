"""Service Registry — env-based URL resolution for peer services.

Each Railway service exposes a health endpoint.  URLs are resolved from
environment variables with sensible local-dev defaults.

    API_BASE_URL   → http://localhost:8000  (port 8000)
    ENGINE_BASE_URL → http://localhost:8081  (port 8081)
    INGEST_BASE_URL → http://localhost:8082  (port 8082)

On Railway, set these to the internal DNS names:
    API_BASE_URL=http://api.railway.internal:8000
    ENGINE_BASE_URL=http://engine.railway.internal:8081
    INGEST_BASE_URL=http://ingest.railway.internal:8082
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServiceEndpoint:
    """Describes a peer service for health probing."""

    name: str
    base_url: str
    health_path: str  # e.g. "/healthz"


def get_peer_services(*, exclude_self: str = "") -> list[ServiceEndpoint]:
    """Return the list of known peer services, excluding *exclude_self*.

    Parameters
    ----------
    exclude_self:
        Service name to omit (the calling service itself).
    """
    all_services = [
        ServiceEndpoint(
            name="api",
            base_url=os.environ.get("API_BASE_URL", "http://localhost:8000"),
            health_path="/healthz",
        ),
        ServiceEndpoint(
            name="engine",
            base_url=os.environ.get("ENGINE_BASE_URL", "http://localhost:8081"),
            health_path="/healthz",
        ),
        ServiceEndpoint(
            name="ingest",
            base_url=os.environ.get("INGEST_BASE_URL", "http://localhost:8082"),
            health_path="/healthz",
        ),
    ]
    if exclude_self:
        return [s for s in all_services if s.name != exclude_self.lower()]
    return all_services
