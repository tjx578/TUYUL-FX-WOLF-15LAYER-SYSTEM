"""
V11 Data Adapter — translates pipeline synthesis output into V11GateInput.

This bridges the gap between the pipeline's Dict[str, Any] output and
the validated V11GateInput model.  Lives in analysis zone only.
"""

from __future__ import annotations

import logging
from typing import Any

from analysis.v11.models import V11GateInput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key mappings: pipeline_key → V11GateInput field
# Supports multiple aliases per field (first match wins).
# ---------------------------------------------------------------------------
_SCORE_ALIASES: dict[str, list[str]] = {
    "wolf_score": ["wolf_score", "wolf", "scores.wolf", "synthesis.wolf_score"],
    "tii_score": ["tii_score", "tii", "scores.tii", "synthesis.tii_score"],
    "frpc_score": ["frpc_score", "frpc", "scores.frpc", "synthesis.frpc_score"],
    "confluence_score": [
        "confluence_score",
        "confluence",
        "scores.confluence",
        "synthesis.confluence_score",
        "overall_score",
    ],
}

_BOOL_ALIASES: dict[str, list[str]] = {
    "htf_alignment": ["htf_alignment", "htf_aligned", "htf.aligned", "context.htf_alignment"],
    "session_valid": ["session_valid", "session.valid", "context.session_valid"],
    "news_clear": ["news_clear", "news.clear", "context.news_clear", "fundamental.news_clear"],
    "momentum_confirmed": [
        "momentum_confirmed",
        "momentum",
        "context.momentum_confirmed",
        "structure.momentum",
    ],
}


def _resolve(data: dict[str, Any], aliases: list[str], default: Any = None) -> Any:
    """Resolve the first matching alias from data, supporting dotted paths."""
    for alias in aliases:
        if "." in alias:
            parts = alias.split(".", 1)
            nested = data.get(parts[0])
            if isinstance(nested, dict):
                val = nested.get(parts[1])
                if val is not None:
                    return val
        else:
            val = data.get(alias)
            if val is not None:
                return val
    return default


class V11DataAdapter:
    """
    Collects data from pipeline synthesis dict and produces a V11GateInput.

    Usage:
        adapter = V11DataAdapter()
        gate_input = adapter.collect(pipeline_output)
    """

    def collect(self, pipeline_data: dict[str, Any]) -> V11GateInput:
        """
        Extract and normalize pipeline synthesis output into V11GateInput.

        Args:
            pipeline_data: raw dict from pipeline synthesis (any shape).

        Returns:
            V11GateInput with validated, clamped values.
            Never raises — returns safe defaults on garbage input.
        """
        if not isinstance(pipeline_data, dict):
            logger.warning("V11DataAdapter.collect: expected dict, got %s", type(pipeline_data).__name__)
            return V11GateInput()

        extracted: dict[str, Any] = {}

        # Resolve score fields
        for field_name, aliases in _SCORE_ALIASES.items():
            extracted[field_name] = _resolve(pipeline_data, aliases, default=0.0)

        # Resolve boolean fields
        for field_name, aliases in _BOOL_ALIASES.items():
            extracted[field_name] = _resolve(pipeline_data, aliases, default=False)

        # Volatility / spread
        extracted["atr_value"] = _resolve(
            pipeline_data, ["atr_value", "atr", "volatility.atr", "context.atr"], default=0.0
        )
        extracted["spread_ratio"] = _resolve(
            pipeline_data, ["spread_ratio", "spread_atr_ratio", "volatility.spread_ratio"], default=0.0
        )

        # Metadata
        extracted["symbol"] = _resolve(pipeline_data, ["symbol", "pair"], default="")
        extracted["timeframe"] = _resolve(pipeline_data, ["timeframe", "tf"], default="")

        result = V11GateInput.from_dict(extracted)

        logger.debug(
            "V11DataAdapter collected for %s/%s: wolf=%.2f tii=%.2f frpc=%.2f conf=%.2f",
            result.symbol,
            result.timeframe,
            result.wolf_score,
            result.tii_score,
            result.frpc_score,
            result.confluence_score,
        )
        return result
