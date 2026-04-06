"""Profile-aware constitution accessor.

This module bridges the two independent config-loading paths
(``config_loader.load_constitution()`` and ``config.constants.get_threshold()``)
by returning constitution values with the active profile's overrides applied.

Consumers can migrate to this module incrementally:

    # Before (not profile-aware):
    from config_loader import load_constitution
    cfg = load_constitution()

    # After (profile-aware):
    from config.effective_constitution import get_effective_constitution
    cfg = get_effective_constitution()

The adapter uses ``ConfigProfileEngine.get_effective_config()`` internally,
so it inherits profile activation, scoped overrides, and deep-merge semantics
already built into the profile engine.
"""

from __future__ import annotations

from typing import Any


def get_effective_constitution() -> dict[str, Any]:
    """Return constitution config with the active profile's overrides merged.

    Falls back to the raw ``CONFIG["constitution"]`` dict when the profile
    engine is unavailable (e.g. import error, early startup).
    """
    try:
        from config.profile_engine import ConfigProfileEngine  # noqa: PLC0415

        effective = ConfigProfileEngine().get_effective_config()
        return dict(effective.get("constitution", {}))
    except Exception:  # noqa: BLE001
        from config_loader import CONFIG  # noqa: PLC0415

        return dict(CONFIG.get("constitution", {}))


def get_effective_threshold(dot_path: str, default: Any = None) -> Any:
    """Profile-aware ``get_threshold()`` replacement.

    Uses dot-notation to traverse the effective constitution dict.

    Examples::

        get_effective_threshold("tii_min", 0.93)
        get_effective_threshold("wolf_30_point.sub_thresholds.fundamental_min", 5)
    """
    keys = dot_path.split(".")
    value: Any = get_effective_constitution()

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default

    return value
