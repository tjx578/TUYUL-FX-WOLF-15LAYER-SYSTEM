"""
Test logging configuration for Railway compatibility.

Verifies that:
- INFO/WARNING logs go to stdout
- ERROR/CRITICAL logs go to stderr
"""

import time
from io import StringIO

from loguru import logger

from config.logging_bootstrap import LogBurstLimiter, LogRateLimiter, resolve_log_level, resolve_stdlib_log_level


def test_split_stream_logging():
    """
    Test that logging is correctly split between stdout and stderr.

    This ensures Railway classifies logs correctly:
    - stdout -> "info" level
    - stderr -> "error" level
    """
    # Remove default handler
    logger.remove()

    # Create string buffers to capture output
    stdout_buffer = StringIO()
    stderr_buffer = StringIO()

    # Add stdout handler for INFO/WARNING (level < 40)
    logger.add(
        stdout_buffer,
        format="{level} | {message}",
        level="INFO",
        filter=lambda record: record["level"].no < 40,
    )

    # Add stderr handler for ERROR/CRITICAL (level >= 40)
    logger.add(
        stderr_buffer,
        format="{level} | {message}",
        level="ERROR",
    )

    # Log messages at different levels
    logger.info("This is an INFO message")
    logger.warning("This is a WARNING message")
    logger.error("This is an ERROR message")
    logger.critical("This is a CRITICAL message")

    # Get output
    stdout_output = stdout_buffer.getvalue()
    stderr_output = stderr_buffer.getvalue()

    # Verify INFO and WARNING went to stdout
    assert "INFO" in stdout_output
    assert "This is an INFO message" in stdout_output
    assert "WARNING" in stdout_output
    assert "This is a WARNING message" in stdout_output

    # Verify ERROR did NOT go to stdout
    assert "ERROR" not in stdout_output
    assert "CRITICAL" not in stdout_output

    # Verify ERROR and CRITICAL went to stderr
    assert "ERROR" in stderr_output
    assert "This is an ERROR message" in stderr_output
    assert "CRITICAL" in stderr_output
    assert "This is a CRITICAL message" in stderr_output

    # Verify INFO and WARNING did NOT go to stderr
    assert "This is an INFO message" not in stderr_output
    assert "This is a WARNING message" not in stderr_output

    # Cleanup
    logger.remove()


def test_level_boundary():
    """
    Test that the level boundary (level.no < 40) correctly separates logs.

    Level numbers:
    - DEBUG: 10
    - INFO: 20
    - WARNING: 30
    - ERROR: 40  <- boundary
    - CRITICAL: 50
    """
    logger.remove()

    stdout_buffer = StringIO()
    stderr_buffer = StringIO()

    logger.add(
        stdout_buffer,
        format="{level} | {message}",
        level="DEBUG",
        filter=lambda record: record["level"].no < 40,
    )

    logger.add(
        stderr_buffer,
        format="{level} | {message}",
        level="ERROR",
    )

    # Test DEBUG (10 < 40) -> stdout
    logger.debug("Debug message")
    assert "Debug message" in stdout_buffer.getvalue()
    assert "Debug message" not in stderr_buffer.getvalue()

    # Clear buffers
    stdout_buffer.truncate(0)
    stdout_buffer.seek(0)
    stderr_buffer.truncate(0)
    stderr_buffer.seek(0)

    # Test ERROR (40 >= 40) -> stderr
    logger.error("Error message")
    assert "Error message" not in stdout_buffer.getvalue()
    assert "Error message" in stderr_buffer.getvalue()

    # Cleanup
    logger.remove()


def test_log_burst_limiter_allows_then_blocks_then_resets():
    limiter = LogBurstLimiter(max_per_window=2, window_seconds=0.2)

    assert limiter.allow("svc", "ERROR", "redis timeout") is True
    assert limiter.allow("svc", "ERROR", "redis timeout") is True
    assert limiter.allow("svc", "ERROR", "redis timeout") is False

    time.sleep(0.25)
    assert limiter.allow("svc", "ERROR", "redis timeout") is True


def test_log_rate_limiter_caps_aggregate_messages_then_resets():
    limiter = LogRateLimiter(max_per_window=2, window_seconds=0.2)

    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is False

    time.sleep(0.25)
    assert limiter.allow() is True


def test_railway_defaults_to_warning_when_log_level_unset(monkeypatch):
    monkeypatch.delenv("WOLF15_LOG_LEVEL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "env_123")

    assert resolve_log_level() == "WARNING"
    assert resolve_stdlib_log_level() == 30


def test_explicit_log_level_overrides_railway_default(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "env_123")
    monkeypatch.setenv("WOLF15_LOG_LEVEL", "INFO")

    assert resolve_log_level() == "INFO"
    assert resolve_stdlib_log_level() == 20
