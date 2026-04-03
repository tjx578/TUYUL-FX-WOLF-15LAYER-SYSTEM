"""Lorentzian Field Stabilizer — output contract.

Analysis-only dataclass. No direction, verdict, position_size, or trade_valid.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LorentzianFieldResult:
    """Immutable, audit-friendly LFS result."""

    e_norm: float
    lrce: float
    gradient_signed: float
    gradient_abs: float
    drift: float
    field_phase: str
    quality_band: str
    rescue_eligible: bool
    confidence_adj: float
    advisory_only: bool = True
