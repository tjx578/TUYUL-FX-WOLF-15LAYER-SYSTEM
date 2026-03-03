from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from typing import Any

from config_loader import CONFIG


@dataclass(frozen=True)
class ConfigProfileState:
    active_profile: str
    locked: bool = False


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
                    cls._instance._scoped_overrides = {
                        "global": {},
                        "account": {},
                        "prop_firm": {},
                        "pair": {},
                    }
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

    def list_scoped_overrides(self) -> dict[str, list[str]]:
        return {
            scope: sorted(items.keys())
            for scope, items in self._scoped_overrides.items()
        }

    def get_active_profile(self) -> str:
        return self._state.active_profile

    def is_locked(self) -> bool:
        return self._state.locked

    def activate(self, profile_name: str) -> dict[str, Any]:
        profile_name = profile_name.strip().lower()
        if profile_name not in self._profiles:
            raise ValueError(f"Unknown profile: {profile_name}")
        if self._state.locked:
            raise ValueError("Config is locked")

        with self._rw_lock:
            self._state = ConfigProfileState(active_profile=profile_name, locked=self._state.locked)
        return {
            "active_profile": self._state.active_profile,
            "effective_config": self.get_effective_config(),
        }

    def set_lock(self, locked: bool) -> dict[str, Any]:
        with self._rw_lock:
            self._state = ConfigProfileState(active_profile=self._state.active_profile, locked=locked)
        return {
            "active_profile": self._state.active_profile,
            "locked": self._state.locked,
        }

    def upsert_override(self, scope: str, key: str, override: dict[str, Any]) -> dict[str, Any]:
        scope_norm = scope.strip().lower()
        if scope_norm not in self._scoped_overrides:
            raise ValueError(f"Unknown scope: {scope}")
        if self._state.locked:
            raise ValueError("Config is locked")
        scope_key = key.strip().upper()
        if not scope_key:
            raise ValueError("Scope key is required")

        with self._rw_lock:
            self._scoped_overrides[scope_norm][scope_key] = deepcopy(override)

        return {
            "scope": scope_norm,
            "key": scope_key,
            "override": deepcopy(self._scoped_overrides[scope_norm][scope_key]),
        }

    def delete_override(self, scope: str, key: str) -> dict[str, Any]:
        scope_norm = scope.strip().lower()
        if scope_norm not in self._scoped_overrides:
            raise ValueError(f"Unknown scope: {scope}")
        if self._state.locked:
            raise ValueError("Config is locked")

        scope_key = key.strip().upper()
        removed = self._scoped_overrides[scope_norm].pop(scope_key, None)
        return {
            "deleted": bool(removed is not None),
            "scope": scope_norm,
            "key": scope_key,
        }

    def get_effective_config(
        self,
        account_id: str | None = None,
        prop_firm: str | None = None,
        pair: str | None = None,
    ) -> dict[str, Any]:
        merged = deepcopy(CONFIG)
        override = deepcopy(self._profiles.get(self._state.active_profile, {}))
        merged = _deep_merge(merged, override)

        global_override = deepcopy(self._scoped_overrides["global"].get("DEFAULT", {}))
        merged = _deep_merge(merged, global_override)

        if account_id:
            merged = _deep_merge(
                merged,
                deepcopy(self._scoped_overrides["account"].get(account_id.strip().upper(), {})),
            )
        if prop_firm:
            merged = _deep_merge(
                merged,
                deepcopy(self._scoped_overrides["prop_firm"].get(prop_firm.strip().upper(), {})),
            )
        if pair:
            merged = _deep_merge(
                merged,
                deepcopy(self._scoped_overrides["pair"].get(pair.strip().upper(), {})),
            )

        return merged


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(dict(base[key]), value)
        else:
            base[key] = value
    return base
