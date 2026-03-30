"""
DEBT-SVC-03: Shared diagnostics hold-alive tests
=================================================
Verifies both sync and async hold-alive variants, timeout behavior,
signal handling, env-var override, and that all 3 call sites use
the shared module instead of copy-pasted inline code.
"""

from __future__ import annotations

import signal
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from services.shared.diagnostics import hold_alive_async, hold_alive_sync

# ── Sync variant ──────────────────────────────────────────────────────────


class TestHoldAliveSync:
    def test_returns_on_timeout(self, monkeypatch):
        """With a very short timeout, hold_alive_sync returns normally."""
        monkeypatch.setenv("DEGRADED_HOLD_TIMEOUT_SEC", "0")
        hold_alive_sync(service_name="TestSync")

    def test_respects_env_timeout(self, monkeypatch):
        """Reads DEGRADED_HOLD_TIMEOUT_SEC from env."""
        monkeypatch.setenv("DEGRADED_HOLD_TIMEOUT_SEC", "1")
        # Should return within ~1s (not hang for 3600s)
        import time

        start = time.monotonic()
        hold_alive_sync(service_name="EnvTest")
        elapsed = time.monotonic() - start
        assert elapsed < 5  # generous upper bound

    def test_returns_on_signal(self, monkeypatch):
        """Simulates SIGINT by setting the internal event from another thread."""
        monkeypatch.setenv("DEGRADED_HOLD_TIMEOUT_SEC", "30")

        original_signal = signal.getsignal(signal.SIGINT)
        handler_ref: list = []

        def _capture_handler(signum, handler):
            if signum == signal.SIGINT:
                handler_ref.append(handler)
            return original_signal

        with patch("services.shared.diagnostics._signal.signal", side_effect=_capture_handler):
            # Run hold_alive_sync in a thread so we can trigger the handler
            result = threading.Event()

            def _run():
                hold_alive_sync(service_name="SigTest")
                result.set()

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            # Wait for the handler to be registered
            import time

            for _ in range(50):
                if handler_ref:
                    break
                time.sleep(0.01)

            if handler_ref:
                # Simulate signal delivery
                handler_ref[-1](signal.SIGINT, None)

            t.join(timeout=5)
            assert result.is_set(), "hold_alive_sync did not exit after signal"

    def test_default_service_name(self, monkeypatch):
        """Default service_name='service' works without error."""
        monkeypatch.setenv("DEGRADED_HOLD_TIMEOUT_SEC", "0")
        hold_alive_sync()  # no service_name kwarg


# ── Async variant ─────────────────────────────────────────────────────────


class TestHoldAliveAsync:
    async def test_returns_on_timeout(self, monkeypatch):
        """With a very short timeout, hold_alive_async returns normally."""
        monkeypatch.setenv("DEGRADED_HOLD_TIMEOUT_SEC", "0")
        await hold_alive_async(service_name="TestAsync")

    async def test_respects_env_timeout(self, monkeypatch):
        """Reads DEGRADED_HOLD_TIMEOUT_SEC from env."""
        monkeypatch.setenv("DEGRADED_HOLD_TIMEOUT_SEC", "1")
        import time

        start = time.monotonic()
        await hold_alive_async(service_name="AsyncEnvTest")
        elapsed = time.monotonic() - start
        assert elapsed < 5

    async def test_default_service_name(self, monkeypatch):
        """Default service_name='service' works without error."""
        monkeypatch.setenv("DEGRADED_HOLD_TIMEOUT_SEC", "0")
        await hold_alive_async()


# ── No inline copy-paste regression ───────────────────────────────────────


class TestNoInlineCopyPaste:
    """All 3 call sites must use services.shared.diagnostics, not inline code."""

    @pytest.mark.parametrize(
        "rel_path",
        [
            "services/engine/runner.py",
            "services/orchestrator/state_manager.py",
            "services/ingest/ingest_worker.py",
        ],
    )
    def test_no_inline_threading_event_hold(self, rel_path):
        """Module must NOT contain an inline 'shutdown = threading.Event()' hold pattern
        outside of services/shared/diagnostics.py."""

        src = (Path(__file__).resolve().parent.parent / rel_path).read_text(encoding="utf-8")
        # The inline pattern always had: shutdown = threading.Event() or shutdown = asyncio.Event()
        # followed by shutdown.wait or asyncio.wait_for inside the same function scope.
        # After refactor, each file should import hold_alive_sync/hold_alive_async instead.
        assert "DEGRADED_HOLD_TIMEOUT_SEC" not in src, (
            f"{rel_path} still reads DEGRADED_HOLD_TIMEOUT_SEC inline — "
            "should delegate to services.shared.diagnostics"
        )

    @pytest.mark.parametrize(
        "rel_path,expected_import",
        [
            ("services/engine/runner.py", "hold_alive_sync"),
            ("services/orchestrator/state_manager.py", "hold_alive_sync"),
            ("services/ingest/ingest_worker.py", "hold_alive_async"),
        ],
    )
    def test_imports_shared_diagnostics(self, rel_path, expected_import):
        """Each call site must import the correct hold_alive variant from shared."""
        src = (Path(__file__).resolve().parent.parent / rel_path).read_text(encoding="utf-8")
        assert expected_import in src, (
            f"{rel_path} does not import {expected_import} from services.shared.diagnostics"
        )
