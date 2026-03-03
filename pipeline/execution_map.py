"""Pipeline execution map builder for observability and dashboard heatmaps.

Zone: pipeline/observability only.
No decision authority, no execution side-effects.
"""

from __future__ import annotations

from typing import Any

CANONICAL_LAYER_IDS: tuple[str, ...] = tuple(f"L{i}" for i in range(15))


def build_execution_map(
    *,
    pair: str,
    timestamp: str,
    layers_executed: list[str],
    engines_invoked: list[str],
    halt_reason: str | None,
    constitutional_verdict: str,
) -> dict[str, Any]:
    """Build normalized execution map payload for a single pipeline run."""
    seen_layers: set[str] = set()
    normalized_layers: list[str] = []
    for lid in layers_executed:
        value = str(lid).upper().strip()
        if not value or value in seen_layers:
            continue
        seen_layers.add(value)
        normalized_layers.append(value)

    seen_engines: set[str] = set()
    normalized_engines: list[str] = []
    for engine in engines_invoked:
        value = str(engine).strip()
        if not value or value in seen_engines:
            continue
        seen_engines.add(value)
        normalized_engines.append(value)

    return {
        "pair": str(pair).upper().strip(),
        "timestamp": str(timestamp),
        "layers_executed": normalized_layers,
        "engines_invoked": normalized_engines,
        "halt_reason": halt_reason,
        "constitutional_verdict": str(constitutional_verdict or "UNKNOWN"),
    }
