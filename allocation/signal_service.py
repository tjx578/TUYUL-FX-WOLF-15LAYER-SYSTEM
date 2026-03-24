from __future__ import annotations

import json
import time
from typing import Any

from loguru import logger

from allocation.signal_registry import SignalRegistry
from config_loader import load_pairs
from schemas.signal_contract import FROZEN_SIGNAL_CONTRACT_VERSION, SignalContract
from schemas.validator import validate_signal_contract
from storage.l12_cache import KEY_PREFIX as _L12_KEY_PREFIX
from storage.l12_cache import get_verdict
from storage.redis_client import redis_client

SIGNAL_READY_CHANNEL = "events:signal_ready"


def _build_signal_payload_from_verdict(symbol: str, verdict: dict[str, Any]) -> dict[str, Any] | None:
    """Build a frozen signal contract payload from an L12 verdict dict.

    Returns the payload dict if it passes schema validation, else ``None``.
    This is extracted as a pure helper so both sync and async paths share logic.
    """
    payload: dict[str, Any] = {
        "contract_version": FROZEN_SIGNAL_CONTRACT_VERSION,
        "signal_id": str(verdict.get("signal_id", f"SIG-CACHE-{symbol}")),
        "symbol": symbol,
        "verdict": str(verdict.get("verdict", "HOLD")),
        "confidence": float(verdict.get("confidence", 0.0) or 0.0),
        "direction": verdict.get("direction"),
        "entry_price": _to_opt_float(verdict.get("entry_price")),
        "stop_loss": _to_opt_float(verdict.get("stop_loss")),
        "take_profit_1": _to_opt_float(verdict.get("take_profit_1")),
        "risk_reward_ratio": _to_opt_float(verdict.get("risk_reward_ratio")),
        "scores": {
            "wolf_score": float((verdict.get("scores") or {}).get("wolf_score", 0.0) or 0.0),
            "tii_score": float((verdict.get("scores") or {}).get("tii_score", 0.0) or 0.0),
            "frpc_score": float((verdict.get("scores") or {}).get("frpc_score", 0.0) or 0.0),
        },
        "timestamp": float(verdict.get("timestamp", time.time()) or time.time()),
        "expires_at": _to_opt_float(verdict.get("expires_at")),
    }
    ok, _errors = validate_signal_contract(payload)
    return payload if ok else None


class SignalService:
    """Read/write helper around signal registry with frozen contract enforcement."""

    def __init__(self) -> None:
        self._registry = SignalRegistry()

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        contract = SignalContract(
            signal_id=str(payload.get("signal_id", f"SIG-{int(time.time())}")),
            symbol=str(payload.get("symbol", payload.get("pair", "UNKNOWN"))).upper(),
            verdict=str(payload.get("verdict", "HOLD")),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            direction=payload.get("direction"),
            entry_price=_to_opt_float(payload.get("entry_price")),
            stop_loss=_to_opt_float(payload.get("stop_loss")),
            take_profit_1=_to_opt_float(payload.get("take_profit_1")),
            risk_reward_ratio=_to_opt_float(payload.get("risk_reward_ratio")),
            scores={
                "wolf_score": float((payload.get("scores") or {}).get("wolf_score", 0.0) or 0.0),
                "tii_score": float((payload.get("scores") or {}).get("tii_score", 0.0) or 0.0),
                "frpc_score": float((payload.get("scores") or {}).get("frpc_score", 0.0) or 0.0),
            },
            timestamp=float(payload.get("timestamp", time.time())),
            expires_at=_to_opt_float(payload.get("expires_at")),
        ).as_dict()

        ok, errors = validate_signal_contract(contract)
        if not ok:
            raise ValueError("; ".join(errors))

        self._registry.publish(contract)
        event_payload = {
            "event": "SIGNAL_READY",
            "signal_id": contract.get("signal_id"),
            "symbol": contract.get("symbol"),
            "ts": time.time(),
        }
        try:
            redis_client.publish(SIGNAL_READY_CHANNEL, json.dumps(event_payload))
        except Exception:
            logger.warning(
                "[SignalService] Failed to publish SIGNAL_READY for %s", contract.get("signal_id"), exc_info=True
            )
        return contract

    async def publish_async(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Publish a signal using the async Redis client (non-blocking).

        Builds and validates the frozen contract, persists it to the registry,
        then publishes the SIGNAL_READY notification via the async Redis client
        to avoid blocking the event loop.
        """
        from infrastructure.redis_client import get_client  # avoid circular at module level

        contract = SignalContract(
            signal_id=str(payload.get("signal_id", f"SIG-{int(time.time())}")),
            symbol=str(payload.get("symbol", payload.get("pair", "UNKNOWN"))).upper(),
            verdict=str(payload.get("verdict", "HOLD")),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            direction=payload.get("direction"),
            entry_price=_to_opt_float(payload.get("entry_price")),
            stop_loss=_to_opt_float(payload.get("stop_loss")),
            take_profit_1=_to_opt_float(payload.get("take_profit_1")),
            risk_reward_ratio=_to_opt_float(payload.get("risk_reward_ratio")),
            scores={
                "wolf_score": float((payload.get("scores") or {}).get("wolf_score", 0.0) or 0.0),
                "tii_score": float((payload.get("scores") or {}).get("tii_score", 0.0) or 0.0),
                "frpc_score": float((payload.get("scores") or {}).get("frpc_score", 0.0) or 0.0),
            },
            timestamp=float(payload.get("timestamp", time.time())),
            expires_at=_to_opt_float(payload.get("expires_at")),
        ).as_dict()

        ok, errors = validate_signal_contract(contract)
        if not ok:
            raise ValueError("; ".join(errors))

        self._registry.publish(contract)
        event_payload = {
            "event": "SIGNAL_READY",
            "signal_id": contract.get("signal_id"),
            "symbol": contract.get("symbol"),
            "ts": time.time(),
        }
        try:
            client = await get_client()
            await client.publish(SIGNAL_READY_CHANNEL, json.dumps(event_payload))
        except Exception:
            logger.warning(
                "[SignalService] Failed to async-publish SIGNAL_READY for %s",
                contract.get("signal_id"),
                exc_info=True,
            )
        return contract

    def get(self, signal_id: str) -> dict[str, Any] | None:
        for item in self.list_all():
            if item.get("signal_id") == signal_id:
                return item
        return None

    def list_by_symbol(self, symbol: str) -> list[dict[str, Any]]:
        symbol = symbol.upper()
        return [item for item in self.list_all() if str(item.get("symbol", "")).upper() == symbol]

    def list_all(self) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}

        for item in self._registry.all_signals():
            sid = str(item.get("signal_id", f"NO_ID:{item.get('symbol', 'UNK')}"))
            merged[sid] = item

        for pair in load_pairs():
            symbol = str(pair.get("symbol", "")).upper().strip()
            if not symbol:
                continue
            verdict = get_verdict(symbol)
            if not verdict:
                continue

            built = _build_signal_payload_from_verdict(symbol, verdict)
            if built:
                merged[built["signal_id"]] = built

        return sorted(merged.values(), key=lambda x: float(x.get("timestamp", 0.0)), reverse=True)

    async def list_all_async(self) -> list[dict[str, Any]]:
        """Async variant of ``list_all`` — uses batched Redis ``mget`` to fetch
        all L12 verdict keys in a single round-trip, avoiding N sequential
        blocking calls in async WS handlers.

        Zone: allocation/ — read-only aggregation, no execution side-effects.
        """
        import contextlib
        import json as _json

        from infrastructure.redis_client import get_client  # avoid circular at module level

        merged: dict[str, dict[str, Any]] = {}

        for item in self._registry.all_signals():
            sid = str(item.get("signal_id", f"NO_ID:{item.get('symbol', 'UNK')}"))
            merged[sid] = item

        pairs = load_pairs()
        symbols: list[str] = [
            str(pair.get("symbol", "")).upper().strip() for pair in pairs if str(pair.get("symbol", "")).upper().strip()
        ]

        if symbols:
            keys = [_L12_KEY_PREFIX + sym for sym in symbols]
            try:
                client = await get_client()
                raw_values: list[Any] = await client.mget(*keys)
            except Exception as exc:
                logger.warning("[SignalService] mget failed, falling back to empty verdicts: %s", exc)
                raw_values = [None] * len(symbols)

            for symbol, raw in zip(symbols, raw_values, strict=True):
                if not raw:
                    continue
                verdict: dict[str, Any] | None = None
                with contextlib.suppress(Exception):
                    verdict = _json.loads(raw)
                if not verdict:
                    continue
                built = _build_signal_payload_from_verdict(symbol, verdict)
                if built:
                    merged[built["signal_id"]] = built

        return sorted(merged.values(), key=lambda x: float(x.get("timestamp", 0.0)), reverse=True)

    async def list_by_symbol_async(self, symbol: str) -> list[dict[str, Any]]:
        """Async variant of ``list_by_symbol``."""
        sym_upper = symbol.upper()
        return [item for item in await self.list_all_async() if str(item.get("symbol", "")).upper() == sym_upper]


def _to_opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_price_float(value: Any) -> float | None:
    """Convert to float for price fields (entry, SL, TP).

    Returns ``None`` when the value is ``None``, zero, or negative —
    prices in financial markets are always strictly positive.  Zero is
    produced by L11._fail() during ATR warm-up and must never reach the
    signal schema validator (which enforces ``exclusiveMinimum: 0``).
    """
    result = _to_opt_float(value)
    return result if (result is not None and result > 0) else None
