"""H1/M15-only candle authority adapter for DirectionalThesis P4.

Unlike the legacy full evidence provider this module never constructs an M1
box, entry, stop, target, risk object, or executable trade plan.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from analysis.strategy_5scr_directional_thesis_v1 import candle_evidence_hash
from contracts.strategy_5scr_directional_thesis_v1 import (
    ClosedCandleAuthorityRefV1,
    Direction,
    DirectionalThesisEvidenceV1,
    PressureDirectionAuthorityV1,
    RouteDirectionAuthorizationV1,
)


def _sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("candle timestamp must include UTC offset")
    return value.astimezone(UTC)


def candle_authority_from_row(row: Mapping[str, Any]) -> ClosedCandleAuthorityRefV1:
    """Freeze a mutable canonical selection row into immutable proof evidence."""

    material_payload = {
        "symbol": str(row["symbol"]).upper(),
        "timeframe": str(row["timeframe"]).upper(),
        "open_time_utc": _utc(row["open_time"]),
        "close_time_utc": _utc(row["close_time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
    }
    material_hash = _sha256(material_payload)
    source_hash = str(row["content_hash"])
    if not source_hash.startswith("sha256:"):
        source_hash = "sha256:" + source_hash
    evidence_payload = {
        **material_payload,
        "material_candle_hash": material_hash,
        "volume": float(row.get("volume", 0) or 0),
        "tick_count": int(row.get("tick_count", 0) or 0),
        "source_content_hash": source_hash,
        "canonical_row_id": int(row["id"]),
        "selected_raw_candle_id": int(row["selected_raw_candle_id"]),
        "provider": str(row["selected_provider"]),
        "feed": str(row["selected_feed"]),
        "provider_timestamp_semantics": str(row["provider_timestamp_semantics"]).upper(),
        "selection_policy": str(row["selection_policy"]),
        "selection_rank": int(row["selection_rank"]),
        "is_closed": True,
        "structural_authority": True,
    }
    # Build once with a syntactically valid placeholder, then derive the ID
    # through the exact verifier used by the reducer.  This avoids a subtle
    # ``+00:00`` versus ``Z`` datetime-serialization split between plain
    # ``json.dumps(default=str)`` and Pydantic's JSON projection.
    provisional = ClosedCandleAuthorityRefV1(
        candle_evidence_id="sha256:" + ("0" * 64),
        **evidence_payload,
    )
    return provisional.model_copy(update={"candle_evidence_id": candle_evidence_hash(provisional)})


class StructuralCandleAuthorityStoreV1(Protocol):
    async def load_authoritative_candle_range(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_exclusive_utc: datetime,
        as_of_utc: datetime,
    ) -> Sequence[ClosedCandleAuthorityRefV1]: ...


class Strategy5SCRStructuralProofProviderV1:
    """Load only immutable H1/M15 authority needed by P4."""

    def __init__(self, store: StructuralCandleAuthorityStoreV1) -> None:
        self._store = store

    async def provide(
        self,
        *,
        strategy_lifecycle_id: str,
        context_epoch_id: str,
        symbol: str,
        decision_at_utc: datetime,
        strategy_direction: Direction,
        selected_route: str,
        pressure_authority: PressureDirectionAuthorityV1,
        coverage_start_at_utc: datetime,
        route_authorization: RouteDirectionAuthorizationV1 | None = None,
        source_request_id: str | None = None,
    ) -> DirectionalThesisEvidenceV1:
        cutoff = _utc(decision_at_utc)
        coverage_start = _utc(coverage_start_at_utc)
        h1 = await self._store.load_authoritative_candle_range(
            symbol=symbol.upper(), timeframe="H1", start_exclusive_utc=coverage_start, as_of_utc=cutoff
        )
        m15 = await self._store.load_authoritative_candle_range(
            symbol=symbol.upper(), timeframe="M15", start_exclusive_utc=coverage_start, as_of_utc=cutoff
        )
        return DirectionalThesisEvidenceV1(
            strategy_lifecycle_id=strategy_lifecycle_id,
            context_epoch_id=context_epoch_id,
            symbol=symbol.upper(),
            decision_at_utc=cutoff,
            strategy_direction=strategy_direction,
            selected_route=selected_route,
            pressure_authority=pressure_authority,
            route_authorization=route_authorization,
            h1_candles=tuple(h1),
            m15_candles=tuple(m15),
            source_request_id=source_request_id,
        )


__all__ = [
    "Strategy5SCRStructuralProofProviderV1",
    "StructuralCandleAuthorityStoreV1",
    "candle_authority_from_row",
]
