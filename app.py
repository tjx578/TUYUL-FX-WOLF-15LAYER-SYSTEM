"""ASGI auto-discovery shim — delegates to ``api_server.app``.

Entrypoint map (the three distinct entrypoints):
  ┌─────────────────┬─────────────────────┬──────────────────────────────┐
  │ Entrypoint      │ Purpose             │ When used                    │
  ├─────────────────┼─────────────────────┼──────────────────────────────┤
  │ app.py          │ ASGI shim (this)    │ ``gunicorn app:app``         │
  │ api_server.py   │ FastAPI + uvicorn   │ ``python api_server.py``     │
  │ main.py         │ Engine orchestrator │ ``python main.py``           │
  └─────────────────┴─────────────────────┴──────────────────────────────┘

``app.py`` and ``api_server.py`` share the *same* FastAPI instance
(created in ``api/app_factory.py``).  ``main.py`` is the engine
process — it embeds the API optionally via RUN_MODE=all.
"""

from api_server import app  # noqa: F401  — re-exported for ASGI discovery

__all__ = ["app"]
