"""
Legacy constitution loader for backward compatibility.

This module is maintained for backward compatibility with existing code
that imports CONSTITUTION_THRESHOLDS directly.

New code should use: from config.constants import get_threshold
"""

# Import from the new unified constants module
from config.constants import CONSTITUTION_THRESHOLDS, get_all_thresholds, get_threshold

__all__ = ["CONSTITUTION_THRESHOLDS", "get_threshold", "get_all_thresholds"]
