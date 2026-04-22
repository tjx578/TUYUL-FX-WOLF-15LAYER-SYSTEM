from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceSnapshot:
    name: str
    score: float
    valid: bool
    confidence: float
    age_seconds: float | None
    publisher_id: str
    schema_version: str
    diagnostics: dict[str, Any]


class SourcePublisher(Protocol):
    name: str

    def build(self, *, symbol: str, trend: str, context: dict[str, Any]) -> SourceSnapshot | None: ...


class _CallablePublisher:
    def __init__(
        self,
        *,
        name: str,
        publisher_id: str,
        schema_version: str,
        build_fn: Callable[..., SourceSnapshot | None],
    ) -> None:
        self.name = name
        self._publisher_id = publisher_id
        self._schema_version = schema_version
        self._build_fn = build_fn

    def build(self, *, symbol: str, trend: str, context: dict[str, Any]) -> SourceSnapshot | None:
        snapshot = self._build_fn(
            symbol=symbol,
            trend=trend,
            context=context,
            publisher_id=self._publisher_id,
            schema_version=self._schema_version,
        )
        if snapshot is None:
            return None
        return snapshot


class SmcPublisher(_CallablePublisher):
    def __init__(self, build_fn: Callable[..., SourceSnapshot | None]) -> None:
        super().__init__(
            name="smc",
            publisher_id="analysis.layers.L9_smc.SmcPublisher",
            schema_version="l9-source-v1",
            build_fn=build_fn,
        )


class LiquidityPublisher(_CallablePublisher):
    def __init__(self, build_fn: Callable[..., SourceSnapshot | None]) -> None:
        super().__init__(
            name="liquidity",
            publisher_id="analysis.layers.L9_smc.LiquidityPublisher",
            schema_version="l9-source-v1",
            build_fn=build_fn,
        )


class DivergencePublisher(_CallablePublisher):
    def __init__(self, build_fn: Callable[..., SourceSnapshot | None]) -> None:
        super().__init__(
            name="divergence",
            publisher_id="analysis.layers.L9_smc.DivergencePublisher",
            schema_version="l9-source-v1",
            build_fn=build_fn,
        )


class SourceBuilderOrchestrator:
    REQUIRED = ("smc", "liquidity", "divergence")
    MAX_SOURCE_AGE_SEC = 15.0

    def __init__(
        self,
        *,
        smc_publisher: SourcePublisher,
        liquidity_publisher: SourcePublisher,
        divergence_publisher: SourcePublisher,
        max_source_age_sec: float | None = None,
    ) -> None:
        self._publishers: dict[str, SourcePublisher] = {
            "smc": smc_publisher,
            "liquidity": liquidity_publisher,
            "divergence": divergence_publisher,
        }
        self._max_source_age_sec = float(max_source_age_sec or self.MAX_SOURCE_AGE_SEC)

    def build_for_l9(self, *, symbol: str, trend: str, context: dict[str, Any]) -> dict[str, Any]:
        snapshots: dict[str, SourceSnapshot] = {}
        diagnostics: dict[str, Any] = {
            "missing": [],
            "stale": [],
            "errored": [],
            "sources": {},
        }
        publisher_metadata: dict[str, dict[str, Any]] = {}

        for name in self.REQUIRED:
            publisher = self._publishers[name]
            try:
                snapshot = publisher.build(symbol=symbol, trend=trend, context=context)
            except Exception as exc:  # noqa: BLE001
                diagnostics["errored"].append({"name": name, "error": str(exc)})
                diagnostics["sources"][name] = {
                    "state": "errored",
                    "reason": str(exc),
                }
                continue

            if snapshot is None:
                diagnostics["missing"].append(name)
                diagnostics["sources"][name] = {
                    "state": "missing",
                    "reason": "publisher_returned_none",
                }
                continue

            publisher_metadata[name] = {
                "publisher_id": snapshot.publisher_id,
                "schema_version": snapshot.schema_version,
                "age_seconds": snapshot.age_seconds,
            }

            if not snapshot.valid:
                diagnostics["missing"].append(name)
                diagnostics["sources"][name] = {
                    "state": "missing",
                    **snapshot.diagnostics,
                }
                continue

            if snapshot.age_seconds is not None and snapshot.age_seconds > self._max_source_age_sec:
                diagnostics["stale"].append(name)
                diagnostics["sources"][name] = {
                    "state": "stale",
                    **snapshot.diagnostics,
                }
                continue

            snapshots[name] = snapshot
            diagnostics["sources"][name] = {
                "state": "ready",
                **snapshot.diagnostics,
            }

        source_flags = {name: (name in snapshots) for name in self.REQUIRED}
        ready_count = sum(1 for state in source_flags.values() if state)
        builder_state = (
            "ready" if ready_count == len(self.REQUIRED) else ("partial" if ready_count > 0 else "not_ready")
        )

        return {
            "structure_sources": source_flags,
            "source_builder_state": builder_state,
            "source_diagnostics": diagnostics,
            "publisher_metadata": publisher_metadata,
            "source_snapshots": {name: asdict(snapshot) for name, snapshot in snapshots.items()},
        }


def derive_candle_age_seconds(candles: list[dict[str, Any]], *, now_ts: float | None = None) -> float | None:
    if not candles:
        return None
    last_ts = candles[-1].get("timestamp")
    ts_value = _coerce_timestamp(last_ts)
    if ts_value is None:
        return None
    now_value = float(now_ts if now_ts is not None else time.time())
    return max(0.0, round(now_value - ts_value, 3))


def _coerce_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return float(text)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    return None


__all__ = [
    "DivergencePublisher",
    "LiquidityPublisher",
    "SmcPublisher",
    "SourceBuilderOrchestrator",
    "SourcePublisher",
    "SourceSnapshot",
    "derive_candle_age_seconds",
]
