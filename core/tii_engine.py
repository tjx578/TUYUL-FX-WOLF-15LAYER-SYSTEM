"""Backward-compatible re-export.  Canonical TII: analysis.l8_tii"""

from analysis.formulas.tii_formula import calculate_tii  # noqa: F401

__all__ = ["calculate_tii"]
