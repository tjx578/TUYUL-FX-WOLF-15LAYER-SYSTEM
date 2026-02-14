"""Engine package facade."""

from __future__ import annotations

from typing import Dict

from engines.quantum_field_engine import QuantumFieldEngine


def create_engine_suite() -> Dict[str, QuantumFieldEngine]:
    """Create default engine suite."""
    return {"field": QuantumFieldEngine()}


__all__ = ["QuantumFieldEngine", "create_engine_suite"]
