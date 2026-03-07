"""
Broker Executor — Dumb execution layer.

This module handles order placement only. It does NOT compute market direction,
override Layer-12 verdicts, or make risk decisions. All state/risk comes from
the dashboard; all authority comes from the constitution (Layer-12).
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from risk.prop_firm import BasePropFirmGuard, GuardResult

__all__ = ["BrokerExecutor"]


class BrokerExecutor:
    """Stateless executor that places orders based on dashboard instructions.

    The executor receives fully-resolved trade instructions (lot size, SL, TP
    already computed by dashboard + prop-firm guard) and simply forwards them
    to the broker API.  It never re-evaluates market conditions or risk.
    """

    def __init__(self, guard: BasePropFirmGuard | None = None) -> None: # type: ignore
        self._guard = guard

    def preflight_check(
        self,
        account_state: dict[str, Any],
        trade_risk: dict[str, Any],
    ) -> GuardResult:
        """Run prop-firm guard before placing an order (advisory only).

        The dashboard is the authority; this is a last-resort safety net.
        """
        if self._guard is None:
            return GuardResult(allowed=True, code="NO_GUARD", severity="info")
        return self._guard.check(account_state, trade_risk)

# ---------------------------------------------------------------------------
# Broker Executor — low-level order placement abstraction.
#
# Wraps MT5 bridge / EA HTTP endpoint calls.
# No strategy logic. No direction computation.
# Execution authority only.
# ---------------------------------------------------------------------------

import hashlib  # noqa: E402
import time  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from enum import StrEnum  # noqa: E402

import httpx  # noqa: E402
from loguru import logger as _loguru_logger  # noqa: E402


class _LoggerLike(Protocol):
    def error(self, message: str, *args: Any, **kwargs: Any) -> Any: ...


logger: _LoggerLike = cast(_LoggerLike, _loguru_logger)


class OrderAction(StrEnum):
    PLACE = "PLACE"
    CANCEL = "CANCEL"
    CLOSE = "CLOSE"
    MODIFY = "MODIFY"


@dataclass
class ExecutionRequest:
    action: OrderAction
    account_id: str
    symbol: str
    lot_size: float
    order_type: str  # BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP | BUY | SELL
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    ticket: int | None = None
    request_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.account_id or not self.account_id.strip():
            raise ValueError("account_id is required for execution requests")
        if not self.request_id:
            raw = f"{self.account_id}:{self.symbol}:{self.entry_price}:{time.time()}"
            self.request_id = hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class ExecutionResult:
    success: bool
    request_id: str
    ticket: int | None = None
    error_code: int = 0
    error_msg: str = ""
    raw: dict[str, Any] | None = None


class BrokerExecutor:  # noqa: F811
    """
    Thin HTTP bridge to the EA (Expert Advisor).

    Sends JSON execution commands to the EA bridge endpoint.
    Never computes direction or risk — that's upstream.
    """

    def __init__(
        self,
        ea_url: str = "http://localhost:8081",
        timeout: float = 10.0,
    ) -> None:
        self._ea_url = ea_url.rstrip("/")
        self._timeout = timeout

    def execute(self, req: ExecutionRequest) -> ExecutionResult:
        """Send a single execution request to EA bridge."""
        payload = {
            "action": req.action,
            "account_id": req.account_id,
            "symbol": req.symbol,
            "lot_size": req.lot_size,
            "order_type": req.order_type,
            "entry_price": req.entry_price,
            "stop_loss": req.stop_loss,
            "take_profit": req.take_profit,
            "ticket": req.ticket,
            "request_id": req.request_id,
            "meta": req.meta,
        }
        try:
            response = httpx.post(
                f"{self._ea_url}/execute",
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            return ExecutionResult(
                success=data.get("success", False),
                request_id=req.request_id,
                ticket=data.get("ticket"),
                error_code=data.get("error_code", 0),
                error_msg=data.get("error_msg", ""),
                raw=data,
            )
        except httpx.HTTPStatusError as exc:
            response = cast(httpx.Response, exc.response)
            status_code = int(response.status_code)
            logger.error(f"BrokerExecutor: HTTP {status_code} for {req.request_id}")
            return ExecutionResult(
                success=False,
                request_id=req.request_id,
                error_code=status_code,
                error_msg=str(exc),
            )
        except Exception as exc:
            logger.error(f"BrokerExecutor: unexpected error for {req.request_id}: {exc}")
            return ExecutionResult(
                success=False,
                request_id=req.request_id,
                error_code=-1,
                error_msg=str(exc),
            )

    def cancel_order(self, account_id: str, ticket: int, symbol: str) -> ExecutionResult:
        req = ExecutionRequest(
            action=OrderAction.CANCEL,
            account_id=account_id,
            symbol=symbol,
            lot_size=0.0,
            order_type="CANCEL",
            ticket=ticket,
        )
        return self.execute(req)

    def close_position(self, account_id: str, ticket: int, symbol: str, lot_size: float) -> ExecutionResult:
        req = ExecutionRequest(
            action=OrderAction.CLOSE,
            account_id=account_id,
            symbol=symbol,
            lot_size=lot_size,
            order_type="CLOSE",
            ticket=ticket,
        )
        return self.execute(req)
