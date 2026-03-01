"""
V11 Configuration Accessor

Loads config/v11.yaml and provides dot-path access following the same
pattern as config/constants.py for the constitution.

Usage:
    from engines.v11.config import get_v11, is_v11_enabled

    score_min = get_v11("selectivity.score_min", 0.78)
    enabled = is_v11_enabled()
"""

from pathlib import Path
from typing import Any

import yaml  # pyright: ignore[reportMissingModuleSource]

BASE_DIR = Path(__file__).resolve().parent.parent.parent / "config"

# Load the v11 YAML file
with open(BASE_DIR / "v11.yaml", encoding="utf-8") as f:
    _V11_CONFIG = yaml.safe_load(f)


def get_v11(dot_path: str, default: Any = None) -> Any:
    """
    Get a v11 configuration value using dot-notation path.

    Examples:
        get_v11("selectivity.score_min", 0.78)
        get_v11("veto.regime_confidence_floor", 0.65)
        get_v11("enabled", True)

    Args:
        dot_path: Dot-separated path to config value (e.g., "selectivity.score_min")
        default: Default value if path not found

    Returns:
        Configuration value or default
    """
    keys = dot_path.split(".")
    value = _V11_CONFIG

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default

    return value


def is_v11_enabled() -> bool:
    """
    Check if v11 suite is enabled.

    Returns:
        True if enabled, False otherwise
    """
    return bool(get_v11("enabled", False))


def get_all_v11_config() -> dict[str, Any]:
    """
    Get the complete v11 configuration.

    Returns:
        Full v11 config dictionary
    """
    return _V11_CONFIG.copy()
