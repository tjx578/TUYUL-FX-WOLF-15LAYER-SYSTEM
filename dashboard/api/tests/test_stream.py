"""
Tests for the SSE /stream/verdicts endpoint.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from dashboard.api.main import app


@pytest.fixture
def sample_verdicts() -> list[dict[str, Any]]:
    return [
        {
            "symbol": "EURUSD",
            "verdict": "EXECUTE",
            "confidence": 0.87,
            "direction": "BUY",
            "entry_price": 1.0850,
            "stop_loss": 1.0820,
            "take_profit_1": 1.0910,
            "rr": 2.0,
            "signal_id": "sig-001",
            "timestamp": "2026-03-01T12:00:00Z",
        },
        {
            "symbol": "GBPUSD",
            "verdict": "HOLD",
            "confidence": 0.52,
        },
    ]


@pytest.mark.asyncio
async def test_stream_verdicts_returns_sse(sample_verdicts: list[dict[str, Any]]):
    """SSE endpoint should return text/event-stream content type."""

    with patch(
        "dashboard.api.routes.stream.get_latest_verdicts",
        new_callable=AsyncMock,
        return_value=sample_verdicts,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:  # noqa: SIM117
            async with client.stream("GET", "/stream/verdicts") as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers["content-type"]

                # Read first SSE frame
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        payload = json.loads(line[6:])
                        assert isinstance(payload, list)
                        assert payload[0]["symbol"] == "EURUSD"
                        assert payload[0]["verdict"] == "EXECUTE"
                        # Dashboard reads only – no mutation fields expected
                        break


@pytest.mark.asyncio
async def test_stream_verdicts_empty_cache():
    """Should stream an empty array when no verdicts are cached."""

    with patch(
        "dashboard.api.routes.stream.get_latest_verdicts",
        new_callable=AsyncMock,
        return_value=[],
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:  # noqa: SIM117
            async with client.stream("GET", "/stream/verdicts") as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    text: str = line
                    if text.startswith("data: "):
                        payload = json.loads(text[6:])
                        assert payload == []
                        break
