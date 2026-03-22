"""
V11 Gate — Validated data models.
Analysis zone only. No execution side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class GateVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"  # insufficient data to evaluate


@dataclass(frozen=True)
class V11GateInput:
    """Validated input for the V11 Extreme Selectivity Gate.

    All fields have safe defaults so missing data never causes a crash.
    The gate will score conservatively (fail-safe) when data is absent.
    """

    # Core scores (0.0–1.0 normalized)
    wolf_score: float = 0.0
    tii_score: float = 0.0
    frpc_score: float = 0.0
    confluence_score: float = 0.0

    # Structure / context flags
    htf_alignment: bool = False
    session_valid: bool = False
    news_clear: bool = True
    momentum_confirmed: bool = False

    # Volatility & spread
    atr_value: float = 0.0
    spread_ratio: float = 0.0  # spread / ATR

    # Optional metadata
    symbol: str = ""
    timeframe: str = ""

    def __post_init__(self) -> None:
        """Clamp scores to valid ranges; raise on truly invalid types."""
        # We use object.__setattr__ because frozen=True
        for fname in ("wolf_score", "tii_score", "frpc_score", "confluence_score"):
            raw = getattr(self, fname)
            if not isinstance(raw, (int, float)):
                raise TypeError(f"{fname} must be numeric, got {type(raw).__name__}")
            clamped = max(0.0, min(1.0, float(raw)))
            object.__setattr__(self, fname, clamped)

        if not isinstance(self.atr_value, (int, float)) or self.atr_value < 0:
            object.__setattr__(self, "atr_value", 0.0)

        if not isinstance(self.spread_ratio, (int, float)) or self.spread_ratio < 0:
            object.__setattr__(self, "spread_ratio", 0.0)

    @staticmethod
    def from_dict(data: dict) -> V11GateInput:
        """Safe constructor from an untyped dict. Never crashes on missing keys."""
        if not isinstance(data, dict):
            return V11GateInput()  # empty → gate will fail-safe

        def _float(key: str, default: float = 0.0) -> float:
            v = data.get(key, default)
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        def _bool(key: str, default: bool = False) -> bool:
            v = data.get(key, default)
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return v > 0
            return default

        return V11GateInput(
            wolf_score=_float("wolf_score"),
            tii_score=_float("tii_score"),
            frpc_score=_float("frpc_score"),
            confluence_score=_float("confluence_score"),
            htf_alignment=_bool("htf_alignment"),
            session_valid=_bool("session_valid"),
            news_clear=_bool("news_clear", default=True),
            momentum_confirmed=_bool("momentum_confirmed"),
            atr_value=_float("atr_value"),
            spread_ratio=_float("spread_ratio"),
            symbol=str(data.get("symbol", "")),
            timeframe=str(data.get("timeframe", "")),
        )


@dataclass(frozen=True)
class V11GateResult:
    """Output of the V11 Extreme Selectivity Gate."""

    verdict: GateVerdict
    overall_score: float  # 0.0–1.0
    passed_checks: int
    total_checks: int
    failed_criteria: tuple[str, ...] = field(default_factory=tuple)
    details: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict == GateVerdict.PASS
