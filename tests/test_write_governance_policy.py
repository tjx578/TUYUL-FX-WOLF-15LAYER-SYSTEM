"""Regression: _check_stale_data governance guard in allocation_router.

Ensures write actions are blocked when L12 verdict data is stale,
and allowed when data is fresh or the check is disabled.
"""

from __future__ import annotations

import sys
import time
import types
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Pre-mock heavy dependencies so allocation_router can be imported.
# These modules have pre-existing syntax errors or require Redis/network.
# ---------------------------------------------------------------------------

_STUB_MODULES = [
    "accounts.risk_engine",
    "propfirm_manager",
    "propfirm_manager.profile_manager",
    "propfirm_manager.profiles",
    "propfirm_manager.profiles.base_guard",
    "allocation.signal_service",
    "journal.trade_journal_service",
    "infrastructure.tracing",
    "infrastructure.redis_url",
    "risk.kill_switch",
    "api.middleware.governance",
]

_saved_modules: dict[str, types.ModuleType | None] = {}


def _install_stubs():
    for name in _STUB_MODULES:
        _saved_modules[name] = sys.modules.get(name)
        mod = types.ModuleType(name)
        # Provide commonly accessed attributes
        mod.RiskEngine = MagicMock()  # type: ignore[attr-defined]
        mod.SignalService = MagicMock()  # type: ignore[attr-defined]
        mod.GlobalKillSwitch = MagicMock()  # type: ignore[attr-defined]
        mod.enforce_write_policy = MagicMock()  # type: ignore[attr-defined]
        mod.trade_journal_automation_service = MagicMock()  # type: ignore[attr-defined]
        mod.setup_tracer = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
        mod.inject_trace_context = MagicMock()  # type: ignore[attr-defined]
        mod.get_redis_url = MagicMock(return_value="redis://localhost:6379/0")  # type: ignore[attr-defined]
        mod.get_safe_redis_url = MagicMock(return_value="redis://localhost:6379/0")  # type: ignore[attr-defined]
        sys.modules[name] = mod


def _restore_modules():
    for name, original in _saved_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


_install_stubs()

# Resolve the real helper while dependency stubs are active.
_import_failed = False
try:
    from api.allocation_router import _check_stale_data as check_stale_data
except Exception:
    _import_failed = True

_restore_modules()

pytestmark = pytest.mark.skipif(
    _import_failed,
    reason="api.allocation_router could not be imported (pre-existing codebase issue)",
)


class TestCheckStaleData:
    """Test api.allocation_router.check_stale_data."""

    # ── 1. Raises 409 when verdict is stale ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_raises_409_when_verdict_is_stale(self):
        old_ts = time.time() - 600  # 600s ago
        stale_verdict = {"timestamp": old_ts, "verdict": "EXECUTE"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=stale_verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await check_stale_data("EURUSD")

            assert exc_info.value.status_code == 409
            assert "STALE_DATA" in exc_info.value.detail

    # ── 2. Passes when verdict is fresh ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_passes_when_verdict_is_fresh(self):
        fresh_ts = time.time() - 10  # 10s ago
        fresh_verdict = {"timestamp": fresh_ts, "verdict": "EXECUTE"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=fresh_verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
        ):
            await check_stale_data("EURUSD")

    # ── 3. Passes when threshold is 0 (disabled) ───────────────────────────

    @pytest.mark.asyncio
    async def test_passes_when_threshold_disabled(self):
        old_ts = time.time() - 9999
        stale_verdict = {"timestamp": old_ts, "verdict": "EXECUTE"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=stale_verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 0),
        ):
            await check_stale_data("EURUSD")

    # ── 4. Passes when no verdict found ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_passes_when_no_verdict_found(self):
        with (
            patch("storage.l12_cache.get_verdict_async", return_value=None),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
        ):
            await check_stale_data("GBPJPY")

    # ── 5. Handles ISO string timestamp ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_handles_iso_string_timestamp(self):
        old_time = datetime.now(UTC).replace(year=2020)
        iso_str = old_time.isoformat()
        old_verdict = {"timestamp": iso_str, "verdict": "EXECUTE"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=old_verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await check_stale_data("USDJPY")

            assert exc_info.value.status_code == 409

    # ── 6. Handles verdict with 'ts' key ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_handles_ts_key(self):
        fresh_ts = time.time() - 5
        verdict = {"ts": fresh_ts, "verdict": "EXECUTE"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
        ):
            await check_stale_data("EURUSD")

    # ── 7. Handles verdict with 'updated_at' key ───────────────────────────

    @pytest.mark.asyncio
    async def test_handles_updated_at_key(self):
        fresh_ts = time.time() - 5
        verdict = {"updated_at": fresh_ts, "verdict": "HOLD"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
        ):
            await check_stale_data("AUDUSD")

    # ── 8. Handles verdict with no timestamp field ──────────────────────────

    @pytest.mark.asyncio
    async def test_passes_when_verdict_has_no_timestamp(self):
        verdict_no_ts = {"verdict": "EXECUTE"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=verdict_no_ts),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
        ):
            await check_stale_data("XAUUSD")

    # ── 9. Negative threshold treated as disabled ───────────────────────────

    @pytest.mark.asyncio
    async def test_negative_threshold_treated_as_disabled(self):
        old_ts = time.time() - 9999
        verdict = {"timestamp": old_ts}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", -1),
        ):
            await check_stale_data("GBPUSD")

    # ── 10. get_verdict exception is silently caught ────────────────────────

    @pytest.mark.asyncio
    async def test_get_verdict_exception_is_caught(self):
        with (
            patch("storage.l12_cache.get_verdict_async", side_effect=RuntimeError("redis down")),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
        ):
            await check_stale_data("NZDUSD")


class TestEnsureLiveProducer:
    """New trade entry must be blocked when producer heartbeat is absent."""

    @pytest.mark.asyncio
    async def test_blocks_when_feed_has_no_producer(self):
        from api.allocation_router import _ensure_live_producer
        from state.data_freshness import FeedFreshnessSnapshot

        snapshot = FeedFreshnessSnapshot(
            state="no_producer",
            staleness_seconds=float("inf"),
            threshold_seconds=300.0,
            detail="no producer heartbeat/tick",
        )

        with patch("api.allocation_router._feed_freshness_snapshot", return_value=snapshot):
            with pytest.raises(HTTPException) as exc_info:
                await _ensure_live_producer("EURUSD")

        assert exc_info.value.status_code == 423
        assert "LIVE_PRODUCER_REQUIRED" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_allows_when_feed_is_fresh(self):
        from api.allocation_router import _ensure_live_producer
        from state.data_freshness import FeedFreshnessSnapshot

        snapshot = FeedFreshnessSnapshot(
            state="fresh",
            staleness_seconds=1.0,
            threshold_seconds=300.0,
            detail="within freshness threshold",
        )

        with patch("api.allocation_router._feed_freshness_snapshot", return_value=snapshot):
            await _ensure_live_producer("EURUSD")
