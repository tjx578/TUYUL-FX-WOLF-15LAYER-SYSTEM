"""Stable overlapping semantics shared by legacy and LIVE pressure sources."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from contracts.strategy_5scr_pressure_emission_v3 import CanonicalPressureEmissionV3


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def sha256_tag(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def semantic_projection(emission: CanonicalPressureEmissionV3) -> dict[str, Any]:
    """Return only facts whose meaning is shared across both adapters.

    Transport/deployment identity and modern-only enrichment are deliberately
    absent.  A missing fact is still explicit ``None``; adapters never invent
    historical provenance to force hash equality.
    """

    return {
        "contract_version": emission.contract_version,
        "symbol": emission.symbol,
        "event_time_utc": emission.time.event_time_utc.isoformat(),
        "pressure": emission.pressure.model_dump(mode="json"),
        "microboost_snapshot": emission.microboost_snapshot.model_dump(mode="json"),
        "reference_price": emission.price.reference_price,
        "reference_price_source": emission.price.reference_price_source,
        "context_seed": {
            "daily_bias": emission.context_seed.daily_bias,
            "h4_structure": emission.context_seed.h4_structure,
            "price_location": emission.context_seed.price_location,
            "liquidity_context": emission.context_seed.liquidity_context,
            "allowed_playbook": emission.context_seed.allowed_playbook,
            "pressure_resolution": emission.context_seed.pressure_resolution,
        },
        "source_safety": emission.source_safety.model_dump(mode="json"),
        "execution_authority": emission.execution_authority,
    }


def semantic_projection_hash(emission: CanonicalPressureEmissionV3) -> str:
    return sha256_tag(semantic_projection(emission))


__all__ = ["canonical_json_bytes", "semantic_projection", "semantic_projection_hash", "sha256_tag"]
