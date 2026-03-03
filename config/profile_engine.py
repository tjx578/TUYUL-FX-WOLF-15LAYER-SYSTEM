from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from typing import Any

from config_loader import CONFIG


@dataclass(frozen=True)
class ConfigProfileState:
    active_profile: str


class ConfigProfileEngine:
    """Runtime config profile selector with deterministic override merge."""

    _instance: "ConfigProfileEngine | None" = None
    _lock = Lock()

    def __new__(cls) -> "ConfigProfileEngine":
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._rw_lock = Lock()
                    cls._instance._profiles = cls._instance._build_profiles()
                    cls._instance._state = ConfigProfileState(active_profile="default")
        return cls._instance

    def _build_profiles(self) -> dict[str, dict[str, Any]]:
        base = {
            "default": {},
            "conservative": {
                "risk": {"position_sizing": {"default_risk_percent": 0.005}},
            },
            "aggressive": {
                "risk": {"position_sizing": {"default_risk_percent": 0.015}},
            },
        }

        yaml_profiles = CONFIG.get("settings", {}).get("profiles", {})
        if isinstance(yaml_profiles, dict):
            for name, override in yaml_profiles.items():
                if isinstance(override, dict):
                    base[str(name)] = override
        return base

    def list_profiles(self) -> list[str]:
        return sorted(self._profiles.keys())

    def get_active_profile(self) -> str:
        return self._state.active_profile

    def activate(self, profile_name: str) -> dict[str, Any]:
        profile_name = profile_name.strip().lower()
        if profile_name not in self._profiles:
            raise ValueError(f"Unknown profile: {profile_name}")

        with self._rw_lock:
            self._state = ConfigProfileState(active_profile=profile_name)
        return {
            "active_profile": self._state.active_profile,
            "effective_config": self.get_effective_config(),
        }

    def get_effective_config(self) -> dict[str, Any]:
        merged = deepcopy(CONFIG)
        override = deepcopy(self._profiles.get(self._state.active_profile, {}))
        return _deep_merge(merged, override)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(dict(base[key]), value)
        else:
            base[key] = value
    return base
