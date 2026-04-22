from __future__ import annotations

from unittest.mock import MagicMock, patch

from execution.broker_executor import BrokerExecutor, ExecutionRequest, ExecutionResult, OrderAction
from execution.ea_manager import EAManager


def _request(request_id: str = "REQ-EXEC-1") -> ExecutionRequest:
    return ExecutionRequest(
        action=OrderAction.PLACE,
        account_id="ACC-001",
        symbol="EURUSD",
        lot_size=0.1,
        order_type="BUY_LIMIT",
        entry_price=1.1,
        stop_loss=1.09,
        take_profit=1.11,
        request_id=request_id,
    )


def test_broker_executor_returns_execution_disabled_contract_without_http() -> None:
    executor = BrokerExecutor()

    with (
        patch.dict("os.environ", {"EXECUTION_ENABLED": "0"}, clear=False),
        patch("execution.broker_executor.httpx.post") as http_post,
    ):
        result = executor.execute(_request())

    assert result.success is False
    assert result.error_msg == "execution_disabled"
    assert result.raw == {
        "sent": False,
        "reason": "execution_disabled",
        "request_id": "REQ-EXEC-1",
    }
    http_post.assert_not_called()


def test_broker_executor_logs_disabled_mode_on_init() -> None:
    with (
        patch.dict("os.environ", {"EXECUTION_ENABLED": "0"}, clear=False),
        patch("execution.broker_executor.logger") as mock_logger,
    ):
        BrokerExecutor(ea_url="http://ea-bridge:8081")

    mock_logger.info.assert_called_with(
        "BrokerExecutor: execution adapter disabled via EXECUTION_ENABLED=0 ea_url={} broker_calls_suppressed=true",
        "http://ea-bridge:8081",
    )


def test_ea_manager_does_not_retry_execution_disabled_result() -> None:
    executor = MagicMock()
    executor.execute.return_value = ExecutionResult(
        success=False,
        request_id="REQ-DISABLED",
        error_msg="execution_disabled",
        raw={"sent": False, "reason": "execution_disabled", "request_id": "REQ-DISABLED"},
    )
    manager = EAManager(executor=executor)

    result = manager._dispatch_with_retry(_request("REQ-DISABLED"))

    assert result.error_msg == "execution_disabled"
    assert executor.execute.call_count == 1
