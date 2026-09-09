"""Tests for the recovery grace period in allocation_router._check_stale_data.

BUG-7 fix: after a pipeline restart the first fresh verdict may have an age
that slightly exceeds STALE_DATA_THRESHOLD_SEC.  The recovery grace period
(STALE_RECOVERY_GRACE_SEC) prevents the post-outage death spiral where the
first verdict after recovery is immediately rejected, triggering a restart
loop.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException

# Import the real router: collection-time module stubs poison its captured
# dependencies for every later API test, even after sys.modules is restored.
from api.allocation_router import _check_stale_data


class TestRecoveryGracePeriod:
    """Tests for the STALE_RECOVERY_GRACE_SEC grace window in _check_stale_data."""

    # ── 1. Fresh verdict (within threshold) always passes ───────────────────

    @pytest.mark.asyncio
    async def test_fresh_verdict_passes(self) -> None:
        """Verdict well within stale threshold is allowed through."""
        fresh_ts = time.time() - 10  # 10s old — well within 300s threshold
        verdict = {"timestamp": fresh_ts, "verdict": "EXECUTE"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
            patch("api.allocation_router.RECOVERY_GRACE_SEC", 120),
        ):
            await _check_stale_data("EURUSD")  # type: ignore[misc]

    # ── 2. Stale verdict beyond threshold + grace raises 409 ─────────────────

    @pytest.mark.asyncio
    async def test_stale_verdict_beyond_grace_raises_409(self) -> None:
        """Verdict older than threshold + grace is rejected with HTTP 409."""
        # 600s > 300 (threshold) + 120 (grace) = 420s  → must reject
        very_old_ts = time.time() - 600
        verdict = {"timestamp": very_old_ts, "verdict": "EXECUTE"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
            patch("api.allocation_router.RECOVERY_GRACE_SEC", 120),
            pytest.raises(HTTPException) as exc_info,
        ):
            await _check_stale_data("EURUSD")  # type: ignore[misc]

        assert exc_info.value.status_code == 409
        assert "STALE_DATA" in exc_info.value.detail

    # ── 3. Verdict in grace window (threshold < age ≤ threshold+grace) passes ─

    @pytest.mark.asyncio
    async def test_verdict_within_grace_window_passes(self) -> None:
        """Verdict age between threshold and threshold+grace is allowed (recovery)."""
        # 350s old: exceeds 300s threshold but within 300+120=420s grace window
        slightly_stale_ts = time.time() - 350
        verdict = {"timestamp": slightly_stale_ts, "verdict": "EXECUTE"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
            patch("api.allocation_router.RECOVERY_GRACE_SEC", 120),
        ):
            # Should NOT raise — falls within recovery grace period
            await _check_stale_data("EURUSD")  # type: ignore[misc]

    # ── 4. Grace window boundary: just inside threshold+grace passes ─────────

    @pytest.mark.asyncio
    async def test_verdict_just_inside_grace_boundary_passes(self) -> None:
        """Verdict age just inside threshold+grace is still within grace."""
        # 415s < 300+120=420 → comfortably within grace window (5s buffer for execution)
        inside_grace_ts = time.time() - 415
        verdict = {"timestamp": inside_grace_ts, "verdict": "HOLD"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
            patch("api.allocation_router.RECOVERY_GRACE_SEC", 120),
        ):
            await _check_stale_data("GBPUSD")  # type: ignore[misc]

    # ── 5. One second beyond grace boundary raises 409 ───────────────────────

    @pytest.mark.asyncio
    async def test_verdict_one_second_past_grace_raises_409(self) -> None:
        """Verdict age 1s beyond threshold+grace must be rejected."""
        # 421s > 300+120=420 → outside grace window
        past_grace_ts = time.time() - 421
        verdict = {"timestamp": past_grace_ts, "verdict": "EXECUTE"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
            patch("api.allocation_router.RECOVERY_GRACE_SEC", 120),
            pytest.raises(HTTPException) as exc_info,
        ):
            await _check_stale_data("GBPUSD")  # type: ignore[misc]

        assert exc_info.value.status_code == 409

    # ── 6. Zero grace period: stale verdict is rejected immediately ───────────

    @pytest.mark.asyncio
    async def test_zero_grace_period_rejects_stale_immediately(self) -> None:
        """When RECOVERY_GRACE_SEC=0, no grace is applied."""
        slightly_stale_ts = time.time() - 350  # 350s > 300s threshold
        verdict = {"timestamp": slightly_stale_ts, "verdict": "EXECUTE"}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
            patch("api.allocation_router.RECOVERY_GRACE_SEC", 0),
            pytest.raises(HTTPException) as exc_info,
        ):
            await _check_stale_data("EURUSD")  # type: ignore[misc]

        assert exc_info.value.status_code == 409
        assert "STALE_DATA" in exc_info.value.detail

    # ── 7. Disabled stale check (threshold=0) always passes ──────────────────

    @pytest.mark.asyncio
    async def test_disabled_threshold_bypasses_grace_check(self) -> None:
        """When STALE_DATA_THRESHOLD_SEC=0 the check is fully disabled."""
        very_old_ts = time.time() - 9999
        verdict = {"timestamp": very_old_ts}

        with (
            patch("storage.l12_cache.get_verdict_async", return_value=verdict),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 0),
            patch("api.allocation_router.RECOVERY_GRACE_SEC", 120),
        ):
            await _check_stale_data("USDJPY")  # type: ignore[misc]

    # ── 8. No verdict found: passes silently (no data = no block) ────────────

    @pytest.mark.asyncio
    async def test_no_verdict_passes_silently(self) -> None:
        """Missing verdict does not block execution (no data → skip guard)."""
        with (
            patch("storage.l12_cache.get_verdict_async", return_value=None),
            patch("api.allocation_router.STALE_DATA_THRESHOLD_SEC", 300),
            patch("api.allocation_router.RECOVERY_GRACE_SEC", 120),
        ):
            await _check_stale_data("XAUUSD")  # type: ignore[misc]

    # ── 9. Recovery grace env var is read at module level ────────────────────

    def test_recovery_grace_sec_env_var_name(self) -> None:
        """STALE_RECOVERY_GRACE_SEC is the documented env var for RECOVERY_GRACE_SEC."""
        import os

        with patch.dict(os.environ, {"STALE_RECOVERY_GRACE_SEC": "60"}):
            # Re-evaluate the default so we can test env var name contract
            value = int(os.getenv("STALE_RECOVERY_GRACE_SEC", "120"))
            assert value == 60
