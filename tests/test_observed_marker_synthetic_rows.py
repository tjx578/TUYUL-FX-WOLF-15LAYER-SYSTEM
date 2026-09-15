"""Historical fixture creation must be independent of ambient signing keys."""

import pytest

from contracts.mt5_execution_protocol import ExecutionCommandV1, verify_execution_command
from tests.integration.test_observed_marker_migration_postgres import (
    HISTORICAL_TIME,
    SECRET,
    _synthetic_row,
    historical_reconciliation_keys,  # noqa: F401 - pytest fixture registration
)


@pytest.mark.parametrize("state, terminal", [("COMPLETED", True), ("QUEUED", False)])
def test_historical_rows_use_fixture_keys_and_remain_signed(state, terminal):
    row = _synthetic_row("offline-contract", state, terminal=terminal)
    command = ExecutionCommandV1.model_validate(row["payload"])
    assert verify_execution_command(command, secret=SECRET)
    assert row["issued_at"] == HISTORICAL_TIME
    assert row["state"] == state
    assert (row["terminal_at"] is not None) is terminal
    assert row["source_event"] == "ENGINEERING_DEMO_CANARY"
