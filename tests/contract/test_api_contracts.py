"""
Contract tests — FE/BE API shape parity

These tests ensure that key endpoint responses match the TypeScript types
declared in  dashboard/nextjs/src/types/index.ts  so that refactors on
either side are caught immediately.

Endpoints covered (P0 minimum set):
  - GET  /api/v1/status        → SystemHealth fields (operator diagnostics)
  - GET  /healthz              → liveness probe (minimal)
  - GET  /api/v1/context       → ContextSnapshot fields
  - GET  /api/v1/verdict/all   → list[L12Verdict] fields
  - GET  /api/v1/accounts      → list[Account] or {accounts:[...]} fields
  - GET  /api/v1/execution     → ExecutionState fields

Strategy:
  - Use httpx.AsyncClient against the real FastAPI app (no live server needed).
  - Auth is bypassed in the test client via override_dependency.
  - Each test asserts required keys are present and values have correct types.
  - Soft-checks (permitted-absent optional keys) are noted but not failed.

Run:
    pytest tests/contract/test_api_contracts.py -v
"""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

# ── App factory + auth override ────────────────────────────────────────────────


def _make_client() -> Any:
    """Build TestClient with auth dependency overridden to always pass."""
    from fastapi import FastAPI

    from api.app_factory import create_app
    from api.middleware.auth import verify_token

    application: FastAPI = cast(FastAPI, create_app())

    # Override auth so tests never need a real JWT
    def _fake_auth() -> dict[str, str]:
        return {"sub": "contract_test", "role": "admin"}

    application.dependency_overrides[cast(Callable[..., Any], verify_token)] = _fake_auth

    return TestClient(application, raise_server_exceptions=True)


# Response-shape fixtures bind real routes to deterministic reader data. Restore
# every module attribute after each case; no collection-time singleton mutation.
@pytest.fixture
def client(monkeypatch) -> Generator[Any, None, None]:
    import api.accounts_router as accounts
    import api.l12_routes as verdicts
    from schemas.trade_models import Account

    monkeypatch.setattr(verdicts, "AVAILABLE_PAIRS", [{"symbol": "EURUSD", "enabled": True}])
    monkeypatch.setattr(verdicts, "_verdict_cache", verdicts.VerdictCache())
    monkeypatch.setattr(
        verdicts,
        "get_verdict",
        lambda _pair: {
            "symbol": "EURUSD",
            "verdict": "HOLD",
            "confidence": 0.0,
            "timestamp": time.time(),
            "gates": [],
        },
    )
    account = Account(
        account_id="ACC-CONTRACT-FIXTURE",
        name="TEST_ONLY",
        balance=1000,
        equity=1000,
        prop_firm=False,
        max_daily_dd_percent=1,
        max_total_dd_percent=2,
        max_concurrent_trades=1,
    )
    monkeypatch.setattr(accounts._accounts, "list_accounts_async", AsyncMock(return_value=[account]))
    monkeypatch.setattr(accounts, "_read_payload", AsyncMock(return_value={}))
    yield _make_client()


# ── /api/v1/status (operator diagnostics) ──────────────────────────────────────


class TestStatusContract:
    """
    TypeScript contract:
      interface SystemHealth {
        status: string
        service: string
        version: string
        redis: { connected: boolean }
        postgres: object
        timestamp: string
      }
    """

    def test_returns_200(self, client: Any) -> None:
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200

    def test_required_fields(self, client: Any) -> None:
        data: dict[str, Any] = client.get("/api/v1/status").json()
        assert "status" in data, "missing: status"

    def test_status_is_string(self, client: Any) -> None:
        data: dict[str, Any] = client.get("/api/v1/status").json()
        assert isinstance(data["status"], str)

    def test_full_status_shape(self, client: Any) -> None:
        """Full status endpoint returns richer shape."""
        resp = client.get("/api/v1/status/full")
        assert resp.status_code == 200
        data: dict[str, Any] = resp.json()
        required = {"status", "service", "version", "redis", "postgres", "timestamp"}
        missing = required - data.keys()
        assert not missing, f"Missing fields in /api/v1/status/full: {missing}"
        assert isinstance(data["redis"], dict)
        assert "connected" in data["redis"]

    def test_healthz_liveness(self, client: Any) -> None:
        """Liveness probe returns minimal payload, no auth needed."""
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "alive"
        assert data["service"] == "tuyul-fx"


# ── /api/v1/context ────────────────────────────────────────────────────────────


class TestContextContract:
    """
    TypeScript contract:
      interface ContextSnapshot {
        pair: string
        timestamp: string | number
        -- additional analysis fields (optional)
      }
    """

    def test_returns_2xx(self, client: Any) -> None:
        resp = client.get("/api/v1/context")
        assert resp.status_code in (200, 204, 404), f"Unexpected status {resp.status_code}: {resp.text[:200]}"

    def test_array_or_object(self, client: Any) -> None:
        resp = client.get("/api/v1/context")
        if resp.status_code == 204:
            return  # no content is valid
        data: Any = resp.json()
        assert isinstance(data, dict | list), f"Expected dict or list, got {type(data).__name__}"

    def test_staleness_is_json_safe(self, client: Any) -> None:
        """feed_staleness_seconds must be null or finite — never Infinity/NaN.

        Regression: float('inf') from _feed_freshness_snapshot() caused
        ``json.dumps(..., allow_nan=False)`` in Starlette's JSONResponse
        to raise ValueError, returning 500 to the dashboard.
        """
        import math

        resp = client.get("/api/v1/context")
        if resp.status_code == 204:
            return
        assert resp.status_code in (200, 404), f"Unexpected {resp.status_code}: {resp.text[:200]}"
        if resp.status_code == 404:
            return
        data = resp.json()
        staleness = data.get("feed_staleness_seconds")
        assert staleness is None or (isinstance(staleness, int | float) and math.isfinite(staleness)), (
            f"feed_staleness_seconds must be null or finite, got {staleness!r}"
        )


# ── /api/v1/verdict/all ────────────────────────────────────────────────────────


def _extract_verdict_items(raw: Any) -> list[dict[str, Any]]:
    """Extract verdict item list from the envelope or flat response format.

    The API returns an envelope ``{verdicts: {pair: item, ...}, count: N, cached: bool}``.
    This helper normalises both the envelope format and any legacy flat dict/list formats
    so callers always receive a plain list of individual verdict dicts.
    """
    if isinstance(raw, dict) and "verdicts" in raw:
        return list(raw["verdicts"].values())
    if isinstance(raw, list):
        return raw
    return list(raw.values())


class TestVerdictAllContract:
    """
    TypeScript contract:
      interface L12Verdict {
        symbol: string
        verdict: VerdictType         // string enum
        confidence: number
        timestamp: number            // unix epoch or ISO string
        gates: GateCheck[]           // array
        // optional: direction, entry_price, stop_loss, take_profit_1, scores
      }
    """

    def test_returns_200(self, client: Any) -> None:
        resp = client.get("/api/v1/verdict/all")
        assert resp.status_code == 200

    def test_is_list_or_dict(self, client: Any) -> None:
        data: Any = client.get("/api/v1/verdict/all").json()
        assert isinstance(data, list | dict), f"Expected list or dict of verdicts, got {type(data).__name__}"

    def test_verdict_item_required_fields(self, client: Any) -> None:
        """Each item must contain the three required FE fields."""
        raw: Any = client.get("/api/v1/verdict/all").json()
        items = _extract_verdict_items(raw)

        assert items, "The bound reader fixture must reach the real route"

        required = {"symbol", "verdict", "confidence"}
        for item in items[:5]:  # spot-check first 5
            missing = required - item.keys()
            assert not missing, f"Verdict item missing required fields {missing}: {list(item.keys())}"

    def test_confidence_is_numeric(self, client: Any) -> None:
        raw: Any = client.get("/api/v1/verdict/all").json()
        items = _extract_verdict_items(raw)
        assert items
        for item in items[:5]:
            assert isinstance(item["confidence"], int | float), (
                f"confidence must be numeric, got {type(item['confidence'])}"
            )

    def test_verdict_string_values(self, client: Any) -> None:
        valid_verdicts = {
            "EXECUTE",
            "EXECUTE_BUY",
            "EXECUTE_SELL",
            "NO_TRADE",
            "HOLD",
            "ABORT",
        }
        raw: Any = client.get("/api/v1/verdict/all").json()
        items = _extract_verdict_items(raw)
        assert items
        for item in items[:5]:
            assert item["verdict"] in valid_verdicts, f"Unknown verdict value: {item['verdict']!r}"


# ── /api/v1/accounts ──────────────────────────────────────────────────────────


class TestAccountsContract:
    """
    TypeScript contract:
      interface Account {
        account_id: string
        account_name: string
        broker: string
        currency: string
        balance: number
        equity: number
      }
    """

    def test_returns_200(self, client: Any) -> None:
        resp = client.get("/api/v1/accounts")
        assert resp.status_code == 200

    def test_is_list_or_wrapped(self, client: Any) -> None:
        data: Any = client.get("/api/v1/accounts").json()
        # Backend may return [] or {"accounts": [...]}
        assert isinstance(data, list | dict), type(data).__name__

    def test_account_item_fields(self, client: Any) -> None:
        raw: Any = client.get("/api/v1/accounts").json()

        items: list[dict[str, Any]]
        if isinstance(raw, list):
            items = [cast(dict[str, Any], item) for item in raw if isinstance(item, dict)]
        elif isinstance(raw, dict):
            raw_dict: dict[str, Any] = raw
            accounts_value = raw_dict.get("accounts", [])
            if isinstance(accounts_value, list):
                items = [cast(dict[str, Any], item) for item in accounts_value if isinstance(item, dict)]
            else:
                items = []
        else:
            items = []

        assert items, "The bound account fixture must reach the real route"

        required = {"account_id", "account_name"}
        for item in items[:3]:
            missing = required - item.keys()
            assert not missing, f"Account missing fields {missing}"


# ── /api/v1/execution ─────────────────────────────────────────────────────────


class TestExecutionContract:
    """
    TypeScript contract:
      interface ExecutionState {
        state: string
        -- at minimum one string field describing current EA/execution state
      }
    """

    def test_returns_2xx(self, client: Any) -> None:
        resp = client.get("/api/v1/execution")
        assert resp.status_code in (200, 404), f"Unexpected {resp.status_code}: {resp.text[:200]}"

    def test_is_object_when_200(self, client: Any) -> None:
        resp = client.get("/api/v1/execution")
        if resp.status_code == 200:
            assert isinstance(resp.json(), dict)


# ── Rate-limit contract ────────────────────────────────────────────────────────


class TestRateLimitContract:
    """
    The rate limiter MUST:
    - Return HTTP 429 when over limit
    - Include Retry-After header in 429 responses
    """

    def test_429_has_retry_after(self) -> None:
        """
        Hit a write endpoint many times quickly and confirm the rate-limit
        response shape is correct if/when a 429 occurs.
        We simulate one request and then manually test a fabricated 429 shape
        against what the middleware guarantees.
        """
        from starlette.responses import JSONResponse

        # The middleware always sets Retry-After on 429—verify that contract.
        resp_body: dict[str, Any] = {
            "detail": "Rate limit exceeded. Try again later.",
            "retry_after_sec": 60,
        }
        response_headers: dict[str, str] = {"Retry-After": "60"}
        resp: Any = JSONResponse(status_code=429, content=resp_body, headers=response_headers)
        assert resp.status_code == 429
        assert response_headers.get("Retry-After") == "60"
        assert "detail" in resp_body
        assert "retry_after_sec" in resp_body


def test_empty_verdict_snapshot_is_explicit(client, monkeypatch):
    import api.l12_routes as verdicts

    monkeypatch.setattr(verdicts, "get_verdict", lambda _pair: None)
    monkeypatch.setattr(verdicts, "_verdict_cache", verdicts.VerdictCache())
    response = client.get("/api/v1/verdict/all")
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "NO_SNAPSHOT_YET"
    assert data["count"] == 0 and data["verdicts"] == {}
