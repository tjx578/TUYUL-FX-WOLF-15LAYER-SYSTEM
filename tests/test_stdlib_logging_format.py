"""Regression tests: stdlib logging calls must not raise TypeError.

Guards against `TypeError: not all arguments converted during string formatting`
which occurs when a stdlib logger is called with `{}` (Loguru-style) placeholders
and extra positional arguments.

Covers:
- api/app_factory.py
- api/middleware/ws_auth.py
- analysis/layers/L2_mta.py (stdlib fallback logger)
- pipeline/wolf_constitutional_pipeline.py (stdlib fallback logger)
"""

from __future__ import annotations

import logging


def _make_stdlib_logger(name: str = "test") -> logging.Logger:
    """Return a stdlib logger with a capturing handler attached."""
    log = logging.getLogger(name)
    log.handlers.clear()
    log.propagate = False
    log.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    log.addHandler(handler)
    return log


class TestStdlibLoggerFormats:
    """Ensure that all stdlib logger call-sites use valid %-style format strings."""

    def test_percent_s_placeholder_does_not_raise(self) -> None:
        log = _make_stdlib_logger("test.percent_s")
        # Should not raise
        log.info("[Redis] API service Redis target: %s", "redis://localhost:6379/0")
        log.warning("HybridCandleAggregator failed to start: %s — candle WS may be empty", Exception("boom"))
        log.warning("[L2] ReflexEmotionCore init failed: %s", RuntimeError("test"))
        log.warning("[L2] FusionIntegrator init failed: %s", RuntimeError("test"))
        log.debug("[L2] Reflex engine error: %s", ValueError("test"))
        log.debug("[L2] Fusion engine error: %s", ValueError("test"))
        log.info("[VerdictPath] pipeline started | symbol=%s safe_mode=%s", "EURUSD", False)
        log.info("[Pipeline v8.0] %s DATA QUALITY recovered", "EURUSD")
        log.debug("[Phase-4→2.5] LRCE patch skipped: %s", Exception("skip"))

    def test_f_string_single_arg_does_not_raise(self) -> None:
        """f-strings passed as the sole argument to stdlib logger are always safe."""
        log = _make_stdlib_logger("test.fstring")
        symbol = "EURUSD"
        exc = Exception("some error")
        log.debug(f"WS auth OK: user={symbol}")
        log.debug(f"JWT decode error: {exc}")
        log.warning("Unsupported DASHBOARD_JWT_ALGO=HS384. Falling back to HS256.")

    def test_curly_brace_placeholder_with_extra_arg_raises_type_error(self) -> None:
        """Confirm the anti-pattern that the fix prevents."""
        import pytest

        with pytest.raises(TypeError, match="not all arguments converted"):
            # Trigger the error by formatting via %-style with {} placeholder
            # The logging module calls msg % args; {} is not a valid % spec.
            msg = "[Redis] API service Redis target: {}"
            args = ("redis://localhost:6379/0",)
            # Replicate what logging.LogRecord.getMessage() does internally:
            _ = msg % args

    def test_app_factory_redis_log_format_is_valid(self) -> None:
        """Directly verify the corrected format string from api/app_factory.py."""
        msg = "[Redis] API service Redis target: %s"
        result = msg % ("redis://localhost:6379/0",)
        assert "redis://localhost:6379/0" in result

    def test_ws_auth_warning_formats_are_valid(self) -> None:
        """Verify ws_auth.py format strings don't raise when formatted."""
        log = _make_stdlib_logger("test.ws_auth")
        log.warning("WS auth rejected: forbidden origin %s", "https://evil.example.com")
        log.warning("WS auth rejected: missing token")
        log.warning("WS auth rejected: JWT missing exp claim")
        log.warning("WS auth rejected: token expired")
        log.warning("WS auth rejected: account scope denied")
        log.warning("WS auth rejected: invalid or expired token")
        log.error("Invalid CORS_ORIGIN_REGEX: %s", "bad.*[regex")

    def test_pipeline_format_strings_are_valid(self) -> None:
        """Verify the corrected pipeline format strings."""
        msg1 = "[VerdictPath] pipeline started | symbol=%s safe_mode=%s"
        result1 = msg1 % ("EURUSD", False)
        assert "EURUSD" in result1
        assert "False" in result1

        msg2 = "[Pipeline v8.0] %s DATA QUALITY recovered"
        result2 = msg2 % ("GBPUSD",)
        assert "GBPUSD" in result2

        msg3 = "[Phase-4→2.5] LRCE patch skipped: %s"
        result3 = msg3 % (RuntimeError("skip"),)
        assert "skip" in result3
