"""ExecutionGuard freshness severity gating tests."""

from execution.execution_guard import ExecutionGuard


def test_execute_blocks_when_freshness_is_critical() -> None:
    guard = ExecutionGuard()
    guard.set_freshness_severity_provider(lambda _symbol: "CRITICAL")

    result = guard.execute(
        signal_id="sig-1",
        account_id="acct-1",
        symbol="EURUSD",
    )

    assert result.allowed is False
    assert result.code == "FEED_FRESHNESS_BLOCK"


def test_execute_allows_when_freshness_is_medium() -> None:
    guard = ExecutionGuard()
    guard.set_freshness_severity_provider(lambda _symbol: "MEDIUM")

    result = guard.execute(
        signal_id="sig-2",
        account_id="acct-1",
        symbol="EURUSD",
    )

    assert result.allowed is True
    assert result.code == "ALLOW"
