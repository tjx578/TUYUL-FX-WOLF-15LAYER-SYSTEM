from __future__ import annotations

import asyncio
import json
from collections import namedtuple
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from mcp import Client

from ops.mt5_mcp import account_binding, server

EXPECTED_TOOLS = {
    "mt5_account_get",
    "mt5_positions_get",
    "mt5_orders_get",
    "mt5_history_deals_get",
    "mt5_history_orders_get",
}
NOW = datetime(2026, 8, 24, 1, 2, 3, tzinfo=UTC)
TEST_KEY = b"k" * 32
TEST_KEY_ID = "audit-2026-01"

Account = namedtuple(
    "Account",
    "login trade_mode leverage limit_orders margin_so_mode trade_allowed trade_expert margin_mode "
    "currency_digits balance credit profit equity margin margin_free margin_level margin_so_call margin_so_so "
    "currency server company",
)
Terminal = namedtuple("Terminal", "connected path trade_allowed tradeapi_disabled")
Position = namedtuple(
    "Position",
    "ticket time time_msc time_update time_update_msc type magic identifier reason volume price_open sl tp "
    "price_current swap profit symbol comment external_id",
)
Order = namedtuple(
    "Order",
    "ticket time_setup time_setup_msc time_done time_done_msc time_expiration type type_time type_filling state "
    "magic position_id position_by_id reason volume_initial volume_current price_open sl tp price_current "
    "price_stoplimit symbol comment external_id",
)
Deal = namedtuple(
    "Deal",
    "ticket order time time_msc type entry magic position_id reason volume price commission swap profit fee "
    "symbol comment external_id",
)


class FakeMT5:
    def __init__(self, terminal_path: Path, *, initialize_ok: bool = True, empty: bool = False) -> None:
        self.terminal_path = terminal_path
        self.initialize_ok = initialize_ok
        self.empty = empty
        self.calls: list[str] = []

    def initialize(self, path: str, *, timeout: int) -> bool:
        self.calls.append("initialize")
        assert Path(path) == self.terminal_path
        assert timeout == 10_000
        return self.initialize_ok

    def shutdown(self) -> None:
        self.calls.append("shutdown")

    def last_error(self) -> tuple[int, str]:
        return (-10005, "redacted by bridge")

    def terminal_info(self) -> Terminal:
        self.calls.append("terminal_info")
        return Terminal(True, str(self.terminal_path.parent), True, False)

    def version(self) -> tuple[int, int, str]:
        self.calls.append("version")
        return (500, 9999, "24 Aug 2026")

    def account_info(self) -> Account:
        self.calls.append("account_info")
        return Account(
            12345678,
            0,
            100,
            200,
            0,
            True,
            True,
            2,
            2,
            10_000.0,
            0.0,
            12.0,
            10_012.0,
            100.0,
            9_912.0,
            10_012.0,
            50.0,
            20.0,
            "USD",
            "Broker-Demo",
            "Broker",
        )

    def positions_get(self) -> list[Position]:
        self.calls.append("positions_get")
        if self.empty:
            return []
        return [
            Position(
                11,
                int(NOW.timestamp()),
                int(NOW.timestamp() * 1_000),
                int(NOW.timestamp()),
                int(NOW.timestamp() * 1_000),
                1,
                15,
                11,
                0,
                0.1,
                1.0,
                0.9,
                1.1,
                1.02,
                0.0,
                2.0,
                "EURUSD",
                "untrusted comment must not escape",
                "external-secret",
            )
        ]

    def orders_get(self) -> list[Order]:
        self.calls.append("orders_get")
        if self.empty:
            return []
        return [
            Order(
                22,
                int(NOW.timestamp()),
                int(NOW.timestamp() * 1_000),
                0,
                0,
                0,
                2,
                0,
                0,
                1,
                15,
                0,
                0,
                0,
                0.1,
                0.1,
                1.0,
                0.9,
                1.1,
                1.0,
                0.0,
                "EURUSD",
                "untrusted comment must not escape",
                "external-secret",
            )
        ]

    def history_deals_get(self, start: datetime, end: datetime) -> list[Deal]:
        self.calls.append("history_deals_get")
        assert end - start <= timedelta(days=31)
        if self.empty:
            return []
        return [
            Deal(
                33,
                22,
                int(NOW.timestamp()),
                int(NOW.timestamp() * 1_000),
                0,
                1,
                15,
                11,
                0,
                0.1,
                1.01,
                -0.1,
                0.0,
                2.0,
                0.0,
                "EURUSD",
                "untrusted comment must not escape",
                "external-secret",
            )
        ]

    def history_orders_get(self, start: datetime, end: datetime) -> list[Order]:
        self.calls.append("history_orders_get")
        assert end - start <= timedelta(days=31)
        return self.orders_get()

    def dangerous_trade_call(self) -> None:
        raise AssertionError("a write surface was invoked")


def _bridge(
    tmp_path: Path, *, initialize_ok: bool = True, empty: bool = False
) -> tuple[server.MT5ReadOnlyBridge, FakeMT5]:
    terminal = tmp_path / "terminal64.exe"
    terminal.parent.mkdir(parents=True, exist_ok=True)
    terminal.write_bytes(b"MZ")
    fake = FakeMT5(terminal, initialize_ok=initialize_ok, empty=empty)
    process = SimpleNamespace(info={"exe": str(terminal)})
    bridge = server.MT5ReadOnlyBridge(
        terminal,
        mt5_loader=lambda: fake,
        process_iter=lambda _attrs: [process],
        clock=lambda: NOW,
        account_binding_key=TEST_KEY,
        account_binding_key_id=TEST_KEY_ID,
    )
    return bridge, fake


def test_mcp_registry_exposes_only_the_five_read_tools() -> None:
    async def list_tools() -> list[object]:
        async with Client(server.mcp) as client:
            return list((await client.list_tools()).tools)

    tools = asyncio.run(list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True


def test_live_reader_calls_only_read_methods_and_redacts_free_text(tmp_path: Path) -> None:
    bridge, fake = _bridge(tmp_path)

    reports = [
        bridge.account_get(),
        bridge.positions_get(),
        bridge.orders_get(),
        bridge.history_deals_get(limit=10),
        bridge.history_orders_get(limit=10),
    ]

    assert all(report["measurement_state"] == "MEASURED" for report in reports)
    rendered = json.dumps(reports)
    assert "12345678" not in rendered
    assert "login_sha256" not in rendered
    assert "login_last4" not in rendered
    assert "5678" not in rendered
    assert "untrusted comment" not in rendered
    assert "external-secret" not in rendered
    assert "dangerous_trade_call" not in fake.calls
    assert set(fake.calls) <= {
        "initialize",
        "shutdown",
        "terminal_info",
        "version",
        "account_info",
        "positions_get",
        "orders_get",
        "history_deals_get",
        "history_orders_get",
    }


def test_empty_snapshot_is_measured_but_connection_failure_is_not(tmp_path: Path) -> None:
    empty_bridge, _ = _bridge(tmp_path / "empty", empty=True)
    failed_bridge, _ = _bridge(tmp_path / "failed", initialize_ok=False)

    empty = empty_bridge.positions_get()
    failed = failed_bridge.positions_get()

    assert empty["measurement_state"] == "MEASURED_EMPTY"
    assert empty["record_count"] == 0
    assert failed["measurement_state"] == "NOT_MEASURED"
    assert failed["record_count"] is None
    assert failed["error_code"].startswith("MT5_INITIALIZE_FAILED_")


def test_history_window_and_limit_fail_closed_before_native_query(tmp_path: Path) -> None:
    bridge, fake = _bridge(tmp_path)

    too_large = bridge.history_deals_get(
        from_utc="2026-01-01T00:00:00Z",
        to_utc="2026-08-24T00:00:00Z",
    )
    too_many_rows = bridge.history_orders_get(limit=1_001)

    assert too_large["measurement_state"] == "ERROR"
    assert too_large["error_code"] == "HISTORY_WINDOW_TOO_LARGE"
    assert too_many_rows["measurement_state"] == "ERROR"
    assert too_many_rows["error_code"] == "HISTORY_LIMIT_OUT_OF_RANGE"
    assert "history_deals_get" not in fake.calls
    assert "history_orders_get" not in fake.calls


def test_terminal_must_be_running_at_the_exact_pinned_path(tmp_path: Path) -> None:
    terminal = tmp_path / "terminal64.exe"
    terminal.write_bytes(b"MZ")
    fake = FakeMT5(terminal)
    wrong = SimpleNamespace(info={"exe": str(tmp_path / "other" / "terminal64.exe")})
    bridge = server.MT5ReadOnlyBridge(
        terminal,
        mt5_loader=lambda: fake,
        process_iter=lambda _attrs: [wrong],
        clock=lambda: NOW,
        account_binding_key=TEST_KEY,
        account_binding_key_id=TEST_KEY_ID,
    )

    report = bridge.account_get()

    assert report["measurement_state"] == "NOT_MEASURED"
    assert report["error_code"] == "TERMINAL_NOT_RUNNING"
    assert fake.calls == []


def test_missing_hmac_key_fails_closed_without_exposing_login(tmp_path: Path) -> None:
    terminal = tmp_path / "terminal64.exe"
    terminal.write_bytes(b"MZ")
    fake = FakeMT5(terminal)
    process = SimpleNamespace(info={"exe": str(terminal)})
    bridge = server.MT5ReadOnlyBridge(
        terminal,
        mt5_loader=lambda: fake,
        process_iter=lambda _attrs: [process],
        clock=lambda: NOW,
    )

    report = bridge.account_get()

    assert report["measurement_state"] == "NOT_MEASURED"
    assert report["error_code"] == "ACCOUNT_BINDING_KEY_NOT_CONFIGURED"
    assert "12345678" not in json.dumps(report)


def test_all_five_reads_emit_the_same_versioned_hmac_and_terminal_identity(tmp_path: Path) -> None:
    bridge, _ = _bridge(tmp_path)
    reports = [
        bridge.account_get(),
        bridge.positions_get(),
        bridge.orders_get(),
        bridge.history_deals_get(limit=10),
        bridge.history_orders_get(limit=10),
    ]

    expected_identifier = account_binding.identifier(
        secret_key=TEST_KEY,
        key_id=TEST_KEY_ID,
        login=12345678,
        server="Broker-Demo",
    )
    assert {report["account_binding"]["identifier"] for report in reports} == {expected_identifier}
    assert {report["account_binding"]["key_id"] for report in reports} == {TEST_KEY_ID}
    assert {report["account_binding"]["server"] for report in reports} == {"Broker-Demo"}
    assert {report["terminal"]["path_sha256"] for report in reports} == {reports[0]["terminal"]["path_sha256"]}
    assert {tuple(report["terminal"]["version"]) for report in reports} == {tuple(reports[0]["terminal"]["version"])}
