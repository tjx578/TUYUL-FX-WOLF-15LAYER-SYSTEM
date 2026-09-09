"""Resource ownership regression during partially completed ingest startup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_fails", [False, True])
async def test_ws_stop_failure_keeps_shared_redis_open(monkeypatch, stop_fails):
    from ingest import service_runner as runner
    from ingest.finnhub_ws import FinnhubBackgroundDrainError

    cache = SimpleNamespace(aclose=AsyncMock())
    ws = SimpleNamespace(stop=AsyncMock(side_effect=FinnhubBackgroundDrainError("pending") if stop_fails else None))
    monkeypatch.setattr(runner, "get_enabled_symbols", lambda: [])
    monkeypatch.setattr(runner, "connect_redis_with_retry", AsyncMock(return_value=cache))
    monkeypatch.setattr(runner, "bootstrap_cache_and_warmup", AsyncMock(return_value=({}, False, "test")))
    monkeypatch.setattr(runner, "set_startup_mode", lambda **kwargs: None)
    monkeypatch.setattr(runner, "create_finnhub_ws", AsyncMock(return_value=ws))
    monkeypatch.setattr(runner, "HTFRefreshScheduler", MagicMock())
    monkeypatch.setattr(runner, "FormingBarPublisher", MagicMock(return_value=SimpleNamespace(stop=AsyncMock())))
    monkeypatch.setattr(runner, "RestPollFallback", MagicMock(side_effect=RuntimeError("partial_startup_failure")))
    import analysis.tick_pipeline

    monkeypatch.setattr(analysis.tick_pipeline, "set_redis_client", lambda redis: None)
    expected = "shutdown_tasks_not_drained" if stop_fails else "partial_startup_failure"
    with pytest.raises(RuntimeError, match=expected):
        await runner.run_ingest_services(True)
    ws.stop.assert_awaited_once()
    if stop_fails:
        cache.aclose.assert_not_awaited()
    else:
        cache.aclose.assert_awaited_once()
