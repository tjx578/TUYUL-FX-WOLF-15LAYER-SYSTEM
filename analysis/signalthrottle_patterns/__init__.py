"""Golden SignalThrottle pattern registry and matcher."""

from .matcher import match_golden_patterns
from .registry import GOLDEN_PATTERNS, PAIR_ROLE_MAP, get_pattern, pair_role_for_symbol

__all__ = [
    "GOLDEN_PATTERNS",
    "PAIR_ROLE_MAP",
    "get_pattern",
    "match_golden_patterns",
    "pair_role_for_symbol",
]
