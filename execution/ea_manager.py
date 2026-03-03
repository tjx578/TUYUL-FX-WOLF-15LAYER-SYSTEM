"""
EA Manager — manages the EA command queue and broker executor bridge.

Wraps BrokerExecutor with retry, logging, and Redis event emission.
No strategy logic. Execution authority only.
"""
from __future__ import annotations

import json
import time
from queue import Empty, Queue
from threading import Thread
from typing import Any, Optional

from loguru import logger

from execution.broker_executor import BrokerExecutor, ExecutionRequest, ExecutionResult
from execution.execution_guard import ExecutionGuard
from execution.trade_state_enum import TradeState

TRADE_UPDATES_CHANNEL = "trade:updates"
_MAX_RETRIES = 2


class EAManager:
    """
    Manages serialized command dispatch to EA broker bridge.

    - Accepts ExecutionRequests via submit()
    - Processes queue in a background thread
    - Emits trade:updates events on success/failure
    """

    def __init__(
        self,
        executor: Optional[BrokerExecutor] = None,
        guard: Optional[ExecutionGuard] = None,
    ) -> None:
        self._executor = executor or BrokerExecutor()
        self._guard = guard or ExecutionGuard()
        self._queue: Queue[ExecutionRequest] = Queue(maxsize=200)
        self._results: dict[str, ExecutionResult] = {}
        self._running = False
        self._worker_thread: Optional[Thread] = None

    def start(self) -> None:
        """Start background dispatch thread."""
        self._running = True
        self._worker_thread = Thread(target=self._dispatch_loop, daemon=True, name="ea-dispatch")
        self._worker_thread.start()
        logger.info("EAManager: dispatch thread started")

    def stop(self) -> None:
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)

    def submit(self, req: ExecutionRequest) -> str:
        """Enqueue an execution request. Returns request_id."""
        signal_id = str(req.meta.get("signal_id", "") or "") if req.meta else ""
        gate = self._guard.execute(
            signal_id=signal_id,
            account_id=req.account_id,
            symbol=req.symbol,
        ) if signal_id else self._guard.validate_scope(
            account_id=req.account_id,
            ea_instance_id=str(req.meta.get("ea_instance_id", "") or "") if req.meta else None,
        )
        if not gate.allowed:
            raise ValueError(f"Execution rejected: {gate.code} ({gate.details})")
        self._queue.put(req, timeout=5)
        return req.request_id

    def get_result(self, request_id: str) -> Optional[ExecutionResult]:
        return self._results.get(request_id)

    def _dispatch_loop(self) -> None:
        while self._running:
            try:
                req = self._queue.get(timeout=1.0)
            except Empty:
                continue
            result = self._dispatch_with_retry(req)
            self._results[req.request_id] = result
            self._emit_trade_event(req, result)

    def _dispatch_with_retry(self, req: ExecutionRequest) -> ExecutionResult:
        for attempt in range(1, _MAX_RETRIES + 1):
            result = self._executor.execute(req)
            if result.success:
                logger.info(f"EAManager: OK request_id={req.request_id} ticket={result.ticket}")
                return result
            logger.warning(
                f"EAManager: attempt {attempt}/{_MAX_RETRIES} failed "
                f"request_id={req.request_id} err={result.error_msg}"
            )
            if attempt < _MAX_RETRIES:
                time.sleep(1.0)
        logger.error(f"EAManager: all retries exhausted for request_id={req.request_id}")
        return result  # type: ignore[return-value]

    def _emit_trade_event(self, req: ExecutionRequest, result: ExecutionResult) -> None:
        event_type = "ORDER_PLACED" if result.success else "ORDER_FAILED"
        payload: dict[str, Any] = {
            "event": event_type,
            "request_id": req.request_id,
            "account_id": req.account_id,
            "symbol": req.symbol,
            "action": req.action,
            "lot_size": str(req.lot_size),
            "ticket": str(result.ticket or ""),
            "error_code": str(result.error_code),
            "error_msg": result.error_msg,
        }
        try:
            from storage.redis_client import RedisClient  # noqa: PLC0415
            rc = RedisClient()
            rc.xadd(TRADE_UPDATES_CHANNEL, {k: str(v) for k, v in payload.items()}, maxlen=10000)
        except Exception as exc:
            logger.debug(f"EAManager: Redis emit skipped: {exc}")
