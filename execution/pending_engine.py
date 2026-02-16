"""
⚡ Pending Execution Engine (PRODUCTION)
-------------------------------------------
Submits orders to MT5 or simulated environments.

Modes:
  1. LIVE  -- sends orders via MT5 socket/API
  2. PAPER -- simulates execution with journal logging
  3. DRY   -- validates only, no execution

Constitutional constraints:
  - Execution is DUMB: no strategy logic, no R:R evaluation,
    no pip distance quality checks.
  - All trade authorization comes from L12 verdict (signal_id).
  - Structural safety only: positive prices, SL/TP direction,
    lot within broker limits, entry price > 0.
  - Journal integration: every submission (including rejections)
    is logged as a J3 execution event.

Zone: execution/ -- no analysis, no decision-making.
"""

import hashlib
import json
import logging
import os
import uuid

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

__all__ = [
    "ExecutionMode",
    "OrderRequest",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "PendingEngine",
]


# ── Enums ────────────────────────────────────────────────────────────

class ExecutionMode(StrEnum):
    LIVE = "LIVE"
    PAPER = "PAPER"
    DRY = "DRY"


class OrderType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"


class OrderStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    PENDING = "PENDING"
    DRY_RUN = "DRY_RUN"
    PAPER_FILLED = "PAPER_FILLED"


# ── Buy / Sell classification ────────────────────────────────────────

_BUY_TYPES = frozenset({OrderType.BUY, OrderType.BUY_LIMIT, OrderType.BUY_STOP})
_SELL_TYPES = frozenset({OrderType.SELL, OrderType.SELL_LIMIT, OrderType.SELL_STOP})


# ── Structural Limits (broker-level, NOT strategy) ──────────────────
# These are the absolute broker/platform limits, not analysis constraints.
# Strategy limits (R:R, pip quality) are enforced upstream in L10/L12.

_BROKER_MIN_LOT = 0.01
_BROKER_MAX_LOT = 100.0   # Broker-level absolute max; prop firm may be tighter


# ── Journal Protocol ─────────────────────────────────────────────────

class JournalWriter(Protocol):
    """Protocol for J3 execution journal integration."""

    def write_j3(self, entry: dict[str, Any]) -> None:
        """Append a J3 execution event to the journal."""
        ...


class _InMemoryJournal:
    """Fallback in-memory journal when no external writer is provided."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    def write_j3(self, entry: dict[str, Any]) -> None:
        self._entries.append(entry)

    @property
    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)


# ── Data Classes ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class OrderRequest:
    """Immutable order request.

    The ``signal_id`` field links this execution back to the L12 verdict
    that authorized it.  It is required for traceability.
    """
    signal_id: str
    pair: str
    order_type: OrderType
    lot_size: float
    entry_price: float
    stop_loss: float
    take_profit: float
    comment: str = ""
    magic_number: int = 74001
    slippage_pips: float = 3.0


@dataclass(frozen=True)
class OrderResult:
    """Immutable result of an order execution attempt."""
    status: OrderStatus
    order_id: str
    signal_id: str
    pair: str
    order_type: str
    lot_size: float
    entry_price: float
    stop_loss: float
    take_profit: float
    message: str
    execution_mode: str
    timestamp: str
    errors: tuple = ()  # Frozen requires tuple, not list
    mt5_ticket: int | None = None


# ── Order ID Generation ──────────────────────────────────────────────

def _generate_order_id(signal_id: str) -> str:
    """Generate a unique order ID anchored to the L12 signal_id.

    Uses UUID4 for uniqueness and embeds the signal_id prefix
    for traceability.  NOT based on datetime -- two submissions
    of the same signal are distinguishable.
    """
    unique = uuid.uuid4().hex[:8].upper()
    # Take first 8 chars of signal_id for human readability
    sig_prefix = signal_id[:8] if signal_id else "NOSIG"
    return f"TWF-{sig_prefix}-{unique}"


def _generate_idempotency_key(request: OrderRequest) -> str:
    """Generate a deterministic key for duplicate detection.

    Based on signal_id + order parameters (NOT time).
    Same signal_id + same params = same key = duplicate.
    """
    content = (
        f"{request.signal_id}:"
        f"{request.pair}:"
        f"{request.order_type.value}:"
        f"{request.entry_price}:"
        f"{request.lot_size}:"
        f"{request.stop_loss}:"
        f"{request.take_profit}"
    )
    return hashlib.sha256(content.encode()).hexdigest()[:24]


# ── Engine ───────────────────────────────────────────────────────────

class PendingEngine:
    """Execution engine with multi-mode support.

    This engine is DUMB by design.  It does not evaluate strategy
    quality, R:R ratios, or pip distance adequacy.  It performs
    only structural safety checks (positive prices, lot bounds,
    SL/TP direction consistency) and routes to the appropriate
    execution mode.

    All trade authorization must come from L12 via ``signal_id``.

    Usage::

        engine = PendingEngine(mode=ExecutionMode.PAPER)
        result = engine.submit(order_request)
    """

    def __init__(
        self,
        mode: ExecutionMode | None = None,
        mt5_host: str = "localhost",
        mt5_port: int = 8228,
        journal_writer: JournalWriter | None = None,
        max_lot_override: Optional[float] = None,  # noqa: UP045
        now_factory=None,
    ) -> None:
        """Initialize engine.

        Parameters
        ----------
        mode : ExecutionMode, optional
            Execution mode.  If None, reads from TUYUL_EXECUTION_MODE env
            var, defaulting to DRY.
        mt5_host : str
            MT5 EA listener host (LIVE mode only).
        mt5_port : int
            MT5 EA listener port (LIVE mode only).
        journal_writer : JournalWriter, optional
            External journal writer for J3 integration.
            Falls back to in-memory journal if not provided.
        max_lot_override : float, optional
            Override broker max lot (e.g. from prop firm profile).
        now_factory : callable, optional
            Factory for current UTC time (for testing).
        """
        self.mode = self._resolve_mode(mode)
        self.mt5_host = mt5_host
        self.mt5_port = mt5_port
        self._max_lot = max_lot_override or _BROKER_MAX_LOT
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

        # Idempotency tracking
        self._executed_keys: dict[str, str] = {}  # idempotency_key -> order_id

        # Journal
        self._internal_journal = _InMemoryJournal()
        self._journal_writer: JournalWriter = journal_writer or self._internal_journal

        logger.info(
            "PendingEngine initialized: mode=%s max_lot=%.2f",
            self.mode.value, self._max_lot,
        )

    @staticmethod
    def _resolve_mode(mode: ExecutionMode | None) -> ExecutionMode:
        """Resolve execution mode from parameter or environment."""
        if mode is not None:
            return mode
        env_mode = os.environ.get("TUYUL_EXECUTION_MODE", "DRY").upper().strip()
        try:
            return ExecutionMode(env_mode)
        except ValueError:
            logger.warning(
                "Unknown TUYUL_EXECUTION_MODE='%s', defaulting to DRY", env_mode
            )
            return ExecutionMode.DRY

    def submit(self, request: OrderRequest) -> OrderResult:
        """Submit order through validation -> execution pipeline.

        Steps:
          1. Structural validation (no strategy logic)
          2. Idempotency check (signal_id + params based)
          3. Route to mode-specific executor
          4. Log J3 journal entry (including rejections)

        Every call produces a journal entry -- no silent failures.
        """
        now = self._now_factory()
        order_id = _generate_order_id(request.signal_id)
        idemp_key = _generate_idempotency_key(request)

        # ── Step 1: Structural Validation ──
        errors = self._validate_structural(request)
        if errors:
            result = OrderResult(
                status=OrderStatus.REJECTED,
                order_id=order_id,
                signal_id=request.signal_id,
                pair=request.pair,
                order_type=request.order_type.value,
                lot_size=request.lot_size,
                entry_price=request.entry_price,
                stop_loss=request.stop_loss,
                take_profit=request.take_profit,
                message=f"Structural validation failed: {'; '.join(errors)}",
                execution_mode=self.mode.value,
                timestamp=now.isoformat(),
                errors=tuple(errors),
            )
            self._log_j3(result)
            return result

        # ── Step 2: Idempotency Check ──
        if idemp_key in self._executed_keys:
            existing_id = self._executed_keys[idemp_key]
            result = OrderResult(
                status=OrderStatus.REJECTED,
                order_id=order_id,
                signal_id=request.signal_id,
                pair=request.pair,
                order_type=request.order_type.value,
                lot_size=request.lot_size,
                entry_price=request.entry_price,
                stop_loss=request.stop_loss,
                take_profit=request.take_profit,
                message=f"Duplicate order rejected (original: {existing_id})",
                execution_mode=self.mode.value,
                timestamp=now.isoformat(),
                errors=("DUPLICATE_ORDER",),
            )
            self._log_j3(result)  # Journal ALL rejections
            return result

        # ── Step 3: Mode-Specific Execution ──
        executor = {
            ExecutionMode.DRY: self._execute_dry,
            ExecutionMode.PAPER: self._execute_paper,
            ExecutionMode.LIVE: self._execute_live,
        }[self.mode]

        result = executor(request, order_id, now)

        # ── Step 4: Record and Journal ──
        if result.status not in (OrderStatus.REJECTED,):
            self._executed_keys[idemp_key] = order_id

        self._log_j3(result)
        return result

    def _validate_structural(self, req: OrderRequest) -> list[str]:  # noqa: PLR0912
        """Structural safety checks only.

        This does NOT enforce:
          - R:R minimums (L12 authority)
          - Pip distance quality (L10 authority)
          - Risk percentage (risk/ authority)

        This DOES enforce:
          - Positive prices
          - SL/TP on correct side of entry for order direction
          - Lot within broker bounds
          - Non-empty signal_id
        """
        errors: list[str] = []

        # Signal linkage required
        if not req.signal_id or not req.signal_id.strip():
            errors.append("signal_id is required (L12 verdict linkage)")

        # Price positivity
        if req.entry_price <= 0:
            errors.append(f"entry_price must be positive (got {req.entry_price})")
        if req.stop_loss <= 0:
            errors.append(f"stop_loss must be positive (got {req.stop_loss})")
        if req.take_profit <= 0:
            errors.append(f"take_profit must be positive (got {req.take_profit})")

        # Lot bounds (broker-level)
        if req.lot_size < _BROKER_MIN_LOT:
            errors.append(
                f"lot_size {req.lot_size} below broker min {_BROKER_MIN_LOT}"
            )
        if req.lot_size > self._max_lot:
            errors.append(
                f"lot_size {req.lot_size} exceeds max {self._max_lot}"
            )

        # SL/TP direction consistency
        if req.entry_price > 0 and req.stop_loss > 0 and req.take_profit > 0:
            if req.order_type in _BUY_TYPES:
                if req.stop_loss >= req.entry_price:
                    errors.append("BUY order: SL must be below entry")
                if req.take_profit <= req.entry_price:
                    errors.append("BUY order: TP must be above entry")
            elif req.order_type in _SELL_TYPES:
                if req.stop_loss <= req.entry_price:
                    errors.append("SELL order: SL must be above entry")
                if req.take_profit >= req.entry_price:
                    errors.append("SELL order: TP must be below entry")

        # SL and TP must not equal entry (zero-distance)
        if req.entry_price > 0:
            if req.stop_loss == req.entry_price:
                errors.append("SL cannot equal entry price")
            if req.take_profit == req.entry_price:
                errors.append("TP cannot equal entry price")

        return errors

    def _execute_dry(
        self, req: OrderRequest, order_id: str, now: datetime
    ) -> OrderResult:
        """DRY mode -- validate only, no execution."""
        logger.info(
            "[DRY] Order validated: %s %s %s @ %.5f (signal: %s)",
            order_id, req.order_type.value, req.pair,
            req.entry_price, req.signal_id,
        )
        return OrderResult(
            status=OrderStatus.DRY_RUN,
            order_id=order_id,
            signal_id=req.signal_id,
            pair=req.pair,
            order_type=req.order_type.value,
            lot_size=req.lot_size,
            entry_price=req.entry_price,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            message="DRY RUN -- order validated, not executed",
            execution_mode="DRY",
            timestamp=now.isoformat(),
        )

    def _execute_paper(
        self, req: OrderRequest, order_id: str, now: datetime
    ) -> OrderResult:
        """PAPER mode -- simulate fill at entry price."""
        logger.info(
            "[PAPER] Order filled: %s %s %s %.2f lots @ %.5f (signal: %s)",
            order_id, req.order_type.value, req.pair,
            req.lot_size, req.entry_price, req.signal_id,
        )
        return OrderResult(
            status=OrderStatus.PAPER_FILLED,
            order_id=order_id,
            signal_id=req.signal_id,
            pair=req.pair,
            order_type=req.order_type.value,
            lot_size=req.lot_size,
            entry_price=req.entry_price,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            message=f"PAPER TRADE -- simulated fill at {req.entry_price:.5f}",
            execution_mode="PAPER",
            timestamp=now.isoformat(),
        )

    def _execute_live(
        self, req: OrderRequest, order_id: str, now: datetime
    ) -> OrderResult:
        """LIVE mode -- submit to MT5 via socket/API.

        Protocol: JSON over TCP to MT5 EA listener.
        """
        import socket as sock_mod  # noqa: PLC0415

        payload = json.dumps(OrderRequest).encode() + b"\n"

        # Common rejection builder
        def _reject(msg: str, error_key: str) -> OrderResult:
            logger.error("[LIVE] %s: %s -- %s", error_key, order_id, msg)
            return OrderResult(
                status=OrderStatus.REJECTED,
                order_id=order_id,
                signal_id=req.signal_id,
                pair=req.pair,
                order_type=req.order_type.value,
                lot_size=req.lot_size,
                entry_price=req.entry_price,
                stop_loss=req.stop_loss,
                take_profit=req.take_profit,
                message=msg,
                execution_mode="LIVE",
                timestamp=now.isoformat(),
                errors=(error_key,),
            )

        try:
            with sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_STREAM) as s:
                s.settimeout(10.0)
                s.connect((self.mt5_host, self.mt5_port))
                s.sendall(payload)
                response = s.recv(4096).decode().strip()

            if not response:
                return _reject("MT5 returned empty response", "MT5_EMPTY_RESPONSE")

            resp = json.loads(response)

        except (TimeoutError, ConnectionRefusedError, ConnectionResetError) as e:
            return _reject(f"MT5 connection failed: {e}", "MT5_CONNECTION_FAILED")
        except json.JSONDecodeError as e:
            return _reject(
                f"MT5 returned invalid JSON: {e}", "MT5_INVALID_RESPONSE"
            )
        except OSError as e:
            return _reject(f"Network error: {e}", "MT5_NETWORK_ERROR")

        if resp.get("result") == "OK":
            ticket = resp.get("ticket")
            fill_price = float(resp.get("price", req.entry_price))
            logger.info(
                "[LIVE] Order FILLED: %s ticket=%s price=%.5f",
                order_id, ticket, fill_price,
            )
            return OrderResult(
                status=OrderStatus.FILLED,
                order_id=order_id,
                signal_id=req.signal_id,
                pair=req.pair,
                order_type=req.order_type.value,
                lot_size=req.lot_size,
                entry_price=fill_price,
                stop_loss=req.stop_loss,
                take_profit=req.take_profit,
                message=f"LIVE FILLED -- ticket {ticket}",
                execution_mode="LIVE",
                timestamp=now.isoformat(),
                mt5_ticket=int(ticket) if ticket is not None else None,
            )

        error_msg = resp.get("error", "Unknown MT5 error")
        return _reject(f"MT5 rejected: {error_msg}", f"MT5_REJECTED:{error_msg}")

    def _log_j3(self, result: OrderResult) -> None:
        """Write J3 execution journal entry.

        Every submission -- including rejections and duplicates -- produces
        a journal entry.  No silent failures.
        """
        entry: dict[str, Any] = {
            "journal_type": "J3",
            "order_id": result.order_id,
            "signal_id": result.signal_id,
            "status": result.status.value,
            "pair": result.pair,
            "order_type": result.order_type,
            "lot_size": result.lot_size,
            "entry_price": result.entry_price,
            "stop_loss": result.stop_loss,
            "take_profit": result.take_profit,
            "execution_mode": result.execution_mode,
            "message": result.message,
            "errors": list(result.errors),
            "mt5_ticket": result.mt5_ticket,
            "timestamp": result.timestamp,
        }
        try:
            self._journal_writer.write_j3(entry)
        except Exception:
            # Journal failure must not block execution reporting
            logger.exception("Failed to write J3 journal entry for %s", result.order_id)

    def get_journal(self) -> list[dict[str, Any]]:
        """Return internal journal entries (for testing / debug).

        In production, use the external journal_writer for persistence.
        """
        if isinstance(self._journal_writer, _InMemoryJournal):
            return self._journal_writer.entries
        return []

    @property
    def executed_count(self) -> int:
        """Number of successfully routed (non-rejected) orders."""
        return len(self._executed_keys)
