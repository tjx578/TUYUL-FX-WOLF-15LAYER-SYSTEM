"""
Unified configuration loader for Wolf-15 Layer System.

This module provides a centralized configuration system that loads from
constitution.yaml and provides dot-path access to threshold values.

Usage:
    from config.constants import get_threshold

    TII_MIN = get_threshold("tii.constitutional_min", 0.93)
    WOLF_MIN = get_threshold("wolf_discipline.minimum", 0.75)
"""

from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent

# Load the constitution YAML file
with open(BASE_DIR / "constitution.yaml") as f:
    _CONSTITUTION_CONFIG = yaml.safe_load(f)


def get_threshold(dot_path: str, default: Any = None) -> Any:
    """
    Get a configuration threshold value using dot-notation path.

    Examples:
        get_threshold("tii.constitutional_min", 0.93)
        get_threshold("wolf_discipline.minimum", 0.75)
        get_threshold("tii_min")  # top-level key

    Args:
        dot_path: Dot-separated path to config value (e.g., "tii.constitutional_min")
        default: Default value if path not found

    Returns:
        Configuration value or default
    """
    keys = dot_path.split(".")
    value = _CONSTITUTION_CONFIG

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default

    return value


def get_all_thresholds() -> dict[str, Any]:
    """
    Get the complete constitution configuration.

    Returns:
        Full constitution config dictionary
    """
    return _CONSTITUTION_CONFIG.copy()


# Backward compatibility: Export CONSTITUTION_THRESHOLDS for existing code
CONSTITUTION_THRESHOLDS = _CONSTITUTION_CONFIG
